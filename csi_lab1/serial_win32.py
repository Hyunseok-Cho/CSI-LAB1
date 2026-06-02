from __future__ import annotations

import ctypes
import os
import re
import winreg
from ctypes import wintypes
from typing import Iterable

from .serial_config import SerialConfig


class SerialError(OSError):
    """Raised when a Win32 serial operation fails."""


if os.name == "nt":
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
else:  # pragma: no cover - this project targets Windows COM ports.
    kernel32 = None


INVALID_HANDLE_VALUE = wintypes.HANDLE(-1).value

GENERIC_READ = 0x80000000
GENERIC_WRITE = 0x40000000
OPEN_EXISTING = 3
FILE_ATTRIBUTE_NORMAL = 0x80

NOPARITY = 0
ODDPARITY = 1
EVENPARITY = 2
ONESTOPBIT = 0
TWOSTOPBITS = 2

DTR_CONTROL_ENABLE = 1
DTR_CONTROL_HANDSHAKE = 2
RTS_CONTROL_ENABLE = 1
RTS_CONTROL_HANDSHAKE = 2

SETDTR = 5
CLRDTR = 6
SETRTS = 3
CLRRTS = 4

MS_CTS_ON = 0x0010
MS_DSR_ON = 0x0020
MS_RING_ON = 0x0040
MS_RLSD_ON = 0x0080

PURGE_TXCLEAR = 0x0004
PURGE_RXCLEAR = 0x0008


class DCB(ctypes.Structure):
    _fields_ = [
        ("DCBlength", wintypes.DWORD),
        ("BaudRate", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("wReserved", wintypes.WORD),
        ("XonLim", wintypes.WORD),
        ("XoffLim", wintypes.WORD),
        ("ByteSize", wintypes.BYTE),
        ("Parity", wintypes.BYTE),
        ("StopBits", wintypes.BYTE),
        ("XonChar", ctypes.c_char),
        ("XoffChar", ctypes.c_char),
        ("ErrorChar", ctypes.c_char),
        ("EofChar", ctypes.c_char),
        ("EvtChar", ctypes.c_char),
        ("wReserved1", wintypes.WORD),
    ]


class COMMTIMEOUTS(ctypes.Structure):
    _fields_ = [
        ("ReadIntervalTimeout", wintypes.DWORD),
        ("ReadTotalTimeoutMultiplier", wintypes.DWORD),
        ("ReadTotalTimeoutConstant", wintypes.DWORD),
        ("WriteTotalTimeoutMultiplier", wintypes.DWORD),
        ("WriteTotalTimeoutConstant", wintypes.DWORD),
    ]


def _configure_api() -> None:
    if kernel32 is None:
        return
    kernel32.CreateFileW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    kernel32.CreateFileW.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    kernel32.GetCommState.argtypes = [wintypes.HANDLE, ctypes.POINTER(DCB)]
    kernel32.GetCommState.restype = wintypes.BOOL
    kernel32.SetCommState.argtypes = [wintypes.HANDLE, ctypes.POINTER(DCB)]
    kernel32.SetCommState.restype = wintypes.BOOL
    kernel32.SetCommTimeouts.argtypes = [wintypes.HANDLE, ctypes.POINTER(COMMTIMEOUTS)]
    kernel32.SetCommTimeouts.restype = wintypes.BOOL
    kernel32.ReadFile.argtypes = [
        wintypes.HANDLE,
        wintypes.LPVOID,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
        wintypes.LPVOID,
    ]
    kernel32.ReadFile.restype = wintypes.BOOL
    kernel32.WriteFile.argtypes = [
        wintypes.HANDLE,
        wintypes.LPCVOID,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
        wintypes.LPVOID,
    ]
    kernel32.WriteFile.restype = wintypes.BOOL
    kernel32.EscapeCommFunction.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel32.EscapeCommFunction.restype = wintypes.BOOL
    kernel32.GetCommModemStatus.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel32.GetCommModemStatus.restype = wintypes.BOOL
    kernel32.PurgeComm.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel32.PurgeComm.restype = wintypes.BOOL


_configure_api()


def _raise_last_error(action: str) -> None:
    code = ctypes.get_last_error()
    raise SerialError(code, f"{action} failed with Win32 error {code}")


def _win32_port_name(port: str) -> str:
    port = port.strip()
    if port.startswith("\\\\.\\"):
        return port
    return "\\\\.\\" + port.upper()


def _natural_key(value: str) -> tuple[object, ...]:
    parts: list[object] = []
    for part in re.split(r"(\d+)", value):
        if part.isdigit():
            parts.append(int(part))
        elif part:
            parts.append(part.upper())
    return tuple(parts)


def list_serial_ports() -> list[str]:
    """Return COM ports registered by Windows, for example COM5 and COM6."""
    if os.name != "nt":
        return []
    ports: set[str] = set()
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DEVICEMAP\SERIALCOMM") as key:
            index = 0
            while True:
                try:
                    _, value, _ = winreg.EnumValue(key, index)
                except OSError:
                    break
                if isinstance(value, str) and value.upper().startswith("COM"):
                    ports.add(value.upper())
                index += 1
    except OSError:
        pass
    return sorted(ports, key=_natural_key)


def ports_label(ports: Iterable[str]) -> str:
    ports = list(ports)
    return ", ".join(ports) if ports else "(no COM ports found)"


class SerialPort:
    def __init__(self, config: SerialConfig):
        if os.name != "nt":
            raise SerialError("This implementation supports Windows COM ports only.")
        self.config = config.normalized()
        self.handle: int | None = None

    def __enter__(self) -> "SerialPort":
        self.open()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    @property
    def is_open(self) -> bool:
        return self.handle is not None

    def open(self) -> None:
        if self.handle is not None:
            return
        handle = kernel32.CreateFileW(
            _win32_port_name(self.config.port),
            GENERIC_READ | GENERIC_WRITE,
            0,
            None,
            OPEN_EXISTING,
            FILE_ATTRIBUTE_NORMAL,
            None,
        )
        if handle == INVALID_HANDLE_VALUE:
            _raise_last_error(f"open {self.config.port}")
        self.handle = handle
        try:
            self._apply_config()
            self.clear()
        except Exception:
            self.close()
            raise

    def close(self) -> None:
        if self.handle is not None:
            kernel32.CloseHandle(self.handle)
            self.handle = None

    def _require_handle(self) -> int:
        if self.handle is None:
            raise SerialError("serial port is not open")
        return self.handle

    def _apply_config(self) -> None:
        handle = self._require_handle()
        dcb = DCB()
        dcb.DCBlength = ctypes.sizeof(DCB)
        if not kernel32.GetCommState(handle, ctypes.byref(dcb)):
            _raise_last_error("GetCommState")

        dcb.BaudRate = self.config.baudrate
        dcb.ByteSize = self.config.data_bits
        dcb.Parity = {"N": NOPARITY, "O": ODDPARITY, "E": EVENPARITY}[self.config.parity]
        dcb.StopBits = ONESTOPBIT if self.config.stop_bits == 1 else TWOSTOPBITS
        dcb.XonChar = b"\x11"
        dcb.XoffChar = b"\x13"
        dcb.ErrorChar = b"\x00"
        dcb.EofChar = b"\x00"
        dcb.EvtChar = b"\x00"
        dcb.flags = self._build_dcb_flags()

        if not kernel32.SetCommState(handle, ctypes.byref(dcb)):
            _raise_last_error("SetCommState")

        timeouts = COMMTIMEOUTS()
        timeouts.ReadIntervalTimeout = 20
        timeouts.ReadTotalTimeoutMultiplier = 0
        timeouts.ReadTotalTimeoutConstant = self.config.read_timeout_ms
        timeouts.WriteTotalTimeoutMultiplier = 0
        timeouts.WriteTotalTimeoutConstant = self.config.write_timeout_ms
        if not kernel32.SetCommTimeouts(handle, ctypes.byref(timeouts)):
            _raise_last_error("SetCommTimeouts")

    def _build_dcb_flags(self) -> int:
        flags = 0
        flags |= 1 << 0  # fBinary
        if self.config.parity != "N":
            flags |= 1 << 1  # fParity

        dtr_control = DTR_CONTROL_ENABLE
        rts_control = RTS_CONTROL_ENABLE

        if self.config.flow_control == "dsrdtr":
            flags |= 1 << 3  # fOutxDsrFlow
            dtr_control = DTR_CONTROL_HANDSHAKE
        elif self.config.flow_control == "rtscts":
            flags |= 1 << 2  # fOutxCtsFlow
            rts_control = RTS_CONTROL_HANDSHAKE
        elif self.config.flow_control == "xonxoff":
            flags |= 1 << 8  # fOutX
            flags |= 1 << 9  # fInX

        flags |= 1 << 7  # fTXContinueOnXoff
        flags |= (dtr_control & 0x03) << 4
        flags |= (rts_control & 0x03) << 12
        return flags

    def clear(self) -> None:
        handle = self._require_handle()
        if not kernel32.PurgeComm(handle, PURGE_RXCLEAR | PURGE_TXCLEAR):
            _raise_last_error("PurgeComm")

    def read(self, size: int = 1) -> bytes:
        handle = self._require_handle()
        if size <= 0:
            return b""
        buffer = ctypes.create_string_buffer(size)
        read_count = wintypes.DWORD(0)
        ok = kernel32.ReadFile(handle, buffer, size, ctypes.byref(read_count), None)
        if not ok:
            _raise_last_error("ReadFile")
        return buffer.raw[: read_count.value]

    def write(self, data: bytes) -> int:
        handle = self._require_handle()
        if not data:
            return 0
        buffer = ctypes.create_string_buffer(data, len(data))
        written = wintypes.DWORD(0)
        ok = kernel32.WriteFile(handle, buffer, len(data), ctypes.byref(written), None)
        if not ok:
            _raise_last_error("WriteFile")
        return written.value

    def set_dtr(self, active: bool) -> None:
        handle = self._require_handle()
        if not kernel32.EscapeCommFunction(handle, SETDTR if active else CLRDTR):
            _raise_last_error("EscapeCommFunction DTR")

    def set_rts(self, active: bool) -> None:
        handle = self._require_handle()
        if not kernel32.EscapeCommFunction(handle, SETRTS if active else CLRRTS):
            _raise_last_error("EscapeCommFunction RTS")

    def modem_status(self) -> dict[str, bool]:
        handle = self._require_handle()
        status = wintypes.DWORD(0)
        if not kernel32.GetCommModemStatus(handle, ctypes.byref(status)):
            _raise_last_error("GetCommModemStatus")
        value = status.value
        return {
            "CTS": bool(value & MS_CTS_ON),
            "DSR": bool(value & MS_DSR_ON),
            "RI": bool(value & MS_RING_ON),
            "DCD": bool(value & MS_RLSD_ON),
        }
