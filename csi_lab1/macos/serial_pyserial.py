from __future__ import annotations

from typing import Iterable

from ..common.serial_config import SerialConfig

try:
    import serial
    from serial.tools import list_ports
except ImportError as exc:  # pragma: no cover - depends on host environment.
    serial = None
    list_ports = None
    _IMPORT_ERROR = exc
else:
    _IMPORT_ERROR = None


class SerialError(OSError):
    """Raised when pySerial is unavailable or a serial operation fails."""


def _require_pyserial() -> None:
    if serial is None or list_ports is None:
        raise SerialError(
            "pySerial is required on macOS/Linux. Install it with: "
            "python3 -m pip install -r requirements.txt"
        ) from _IMPORT_ERROR


def list_serial_ports() -> list[str]:
    """Return serial device names, for example /dev/cu.usbserial-xxxx on macOS."""
    _require_pyserial()
    infos = sorted(list_ports.comports(include_links=True))
    devices = [info.device for info in infos]

    # On macOS, /dev/cu.* is the call-out device normally used by applications.
    cu_devices = [device for device in devices if device.startswith("/dev/cu.")]
    return cu_devices or devices


def ports_label(ports: Iterable[str]) -> str:
    ports = list(ports)
    return ", ".join(ports) if ports else "(no serial ports found)"


class SerialPort:
    def __init__(self, config: SerialConfig):
        _require_pyserial()
        self.config = config.normalized()
        self.handle: serial.Serial | None = None

    def __enter__(self) -> "SerialPort":
        self.open()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    @property
    def is_open(self) -> bool:
        return self.handle is not None and self.handle.is_open

    def open(self) -> None:
        if self.handle is not None and self.handle.is_open:
            return
        try:
            self.handle = serial.Serial(
                port=self.config.port,
                baudrate=self.config.baudrate,
                bytesize={7: serial.SEVENBITS, 8: serial.EIGHTBITS}[self.config.data_bits],
                parity={
                    "N": serial.PARITY_NONE,
                    "E": serial.PARITY_EVEN,
                    "O": serial.PARITY_ODD,
                }[self.config.parity],
                stopbits={1: serial.STOPBITS_ONE, 2: serial.STOPBITS_TWO}[self.config.stop_bits],
                timeout=self.config.read_timeout_ms / 1000,
                write_timeout=self.config.write_timeout_ms / 1000,
                xonxoff=self.config.flow_control == "xonxoff",
                rtscts=self.config.flow_control == "rtscts",
                dsrdtr=self.config.flow_control == "dsrdtr",
            )
            self.clear()
        except serial.SerialException as exc:
            self.handle = None
            raise SerialError(str(exc)) from exc

    def close(self) -> None:
        if self.handle is not None:
            self.handle.close()
            self.handle = None

    def _require_handle(self) -> serial.Serial:
        if self.handle is None or not self.handle.is_open:
            raise SerialError("serial port is not open")
        return self.handle

    def clear(self) -> None:
        handle = self._require_handle()
        handle.reset_input_buffer()
        handle.reset_output_buffer()

    def read(self, size: int = 1) -> bytes:
        if size <= 0:
            return b""
        try:
            return self._require_handle().read(size)
        except serial.SerialException as exc:
            raise SerialError(str(exc)) from exc

    def write(self, data: bytes) -> int:
        if not data:
            return 0
        try:
            return self._require_handle().write(data)
        except serial.SerialException as exc:
            raise SerialError(str(exc)) from exc

    def set_dtr(self, active: bool) -> None:
        try:
            self._require_handle().dtr = active
        except serial.SerialException as exc:
            raise SerialError(str(exc)) from exc

    def set_rts(self, active: bool) -> None:
        try:
            self._require_handle().rts = active
        except serial.SerialException as exc:
            raise SerialError(str(exc)) from exc

    def modem_status(self) -> dict[str, bool]:
        handle = self._require_handle()
        return {
            "CTS": bool(handle.cts),
            "DSR": bool(handle.dsr),
            "RI": bool(handle.ri),
            "DCD": bool(handle.cd),
        }
