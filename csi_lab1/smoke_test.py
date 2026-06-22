from __future__ import annotations

import argparse
import time

from .common.cli_common import add_serial_args, format_hex
from .common.serial_config import SerialConfig
from .serial_backend import SerialPort


def read_until(port: SerialPort, expected: bytes, timeout_s: float) -> bytes:
    deadline = time.monotonic() + timeout_s
    buffer = bytearray()
    while time.monotonic() < deadline:
        chunk = port.read(256)
        if chunk:
            buffer.extend(chunk)
            if expected in buffer:
                return bytes(buffer)
    return bytes(buffer)


def build_config(port: str, args: argparse.Namespace) -> SerialConfig:
    return SerialConfig(
        port=port,
        baudrate=args.baud,
        data_bits=args.data_bits,
        parity=args.parity,
        stop_bits=args.stop_bits,
        flow_control=args.flow,
        read_timeout_ms=args.read_timeout_ms,
        write_timeout_ms=args.write_timeout_ms,
    ).normalized()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Open two COM ports and verify null-modem data transfer")
    parser.add_argument("--port-a", required=True, help="first COM port, for example COM5")
    parser.add_argument("--port-b", required=True, help="second COM port, for example COM6")
    add_serial_args(parser, baud=9600, data_bits=8, parity="N", stop_bits=1)
    parser.add_argument("--timeout", type=float, default=2.0)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    config_a = build_config(args.port_a, args)
    config_b = build_config(args.port_b, args)

    message_a = b"CSI_SMOKE_FROM_A\r\n"
    message_b = b"CSI_SMOKE_FROM_B\r\n"

    with SerialPort(config_a) as port_a, SerialPort(config_b) as port_b:
        print(f"Opened A: {config_a.label}")
        print(f"Opened B: {config_b.label}")
        port_a.clear()
        port_b.clear()

        print(f"A -> B TX: {message_a!r}")
        port_a.write(message_a)
        rx_b = read_until(port_b, message_a, args.timeout)
        print(f"B RX HEX: {format_hex(rx_b)}")
        if message_a not in rx_b:
            print("A -> B failed")
            return 1

        print(f"B -> A TX: {message_b!r}")
        port_b.write(message_b)
        rx_a = read_until(port_a, message_b, args.timeout)
        print(f"A RX HEX: {format_hex(rx_a)}")
        if message_b not in rx_a:
            print("B -> A failed")
            return 1

    print("Smoke test passed in both directions.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
