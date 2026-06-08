from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Protocol


COMMAND_WRITE_TEXT = 1
COMMAND_READ_TEXT = 2

EX_ILLEGAL_FUNCTION = 1
EX_ILLEGAL_DATA_ADDRESS = 2
EX_ILLEGAL_DATA_VALUE = 3


class ReadablePort(Protocol):
    def read(self, size: int = 1) -> bytes:
        ...


class ModbusAsciiError(ValueError):
    pass


@dataclass(frozen=True)
class ModbusAsciiFrame:
    address: int
    command: int
    data: bytes = b""

    @property
    def is_broadcast(self) -> bool:
        return self.address == 0

    @property
    def is_exception(self) -> bool:
        return bool(self.command & 0x80)


def validate_address(address: int) -> None:
    if not 0 <= address <= 247:
        raise ValueError("MODBUS address must be in range 0..247")


def lrc(payload: bytes) -> int:
    return (-sum(payload)) & 0xFF


def encode_frame(address: int, command: int, data: bytes = b"") -> bytes:
    validate_address(address)
    if not 0 <= command <= 255:
        raise ValueError("command must fit in one byte")
    payload = bytes([address, command]) + data
    body = payload + bytes([lrc(payload)])
    return b":" + body.hex().upper().encode("ascii") + b"\r\n"


def decode_frame(wire: bytes) -> ModbusAsciiFrame:
    if not wire.startswith(b":"):
        raise ModbusAsciiError("frame does not start with ':'")
    if not wire.endswith(b"\r\n"):
        raise ModbusAsciiError("frame does not end with CRLF")
    hex_body = wire[1:-2].strip()
    if len(hex_body) < 6:
        raise ModbusAsciiError("frame is too short")
    if len(hex_body) % 2:
        raise ModbusAsciiError("hex body length must be even")
    try:
        raw = bytes.fromhex(hex_body.decode("ascii"))
    except ValueError as exc:
        raise ModbusAsciiError("frame body is not valid hexadecimal") from exc
    payload, received_lrc = raw[:-1], raw[-1]
    expected_lrc = lrc(payload)
    if received_lrc != expected_lrc:
        raise ModbusAsciiError(f"bad LRC: received {received_lrc:02X}, expected {expected_lrc:02X}")
    return ModbusAsciiFrame(address=payload[0], command=payload[1], data=payload[2:])


def encode_exception(address: int, command: int, exception_code: int) -> bytes:
    return encode_frame(address, command | 0x80, bytes([exception_code]))


def format_wire_hex(wire: bytes) -> str:
    return " ".join(f"{byte:02X}" for byte in wire)


def read_ascii_frame(
    port: ReadablePort,
    *,
    inter_char_timeout_s: float = 0.2,
    deadline: float | None = None,
    max_len: int = 1024,
    stop_event: object | None = None,
) -> bytes | None:
    """Read one MODBUS-ASCII frame or return None on transaction timeout."""
    buffer = bytearray()
    last_byte_at: float | None = None

    while True:
        if stop_event is not None and getattr(stop_event, "is_set")():
            return None
        now = time.monotonic()
        if deadline is not None and now >= deadline:
            return None

        chunk = port.read(1)
        if not chunk:
            continue

        now = time.monotonic()
        if (
            buffer
            and inter_char_timeout_s > 0
            and last_byte_at is not None
            and now - last_byte_at > inter_char_timeout_s
        ):
            buffer.clear()

        last_byte_at = now
        byte = chunk[0]

        if not buffer:
            if byte == ord(":"):
                buffer.append(byte)
            continue

        buffer.append(byte)
        if len(buffer) > max_len:
            buffer.clear()
            continue
        if buffer.endswith(b"\r\n"):
            return bytes(buffer)


def bytes_to_text(data: bytes, encoding: str = "utf-8") -> str:
    return data.decode(encoding, errors="replace")
