from __future__ import annotations

import argparse

from .serial_config import FLOW_CONTROLS, SerialConfig
from ..serial_backend import list_serial_ports, ports_label


def add_serial_args(
    parser: argparse.ArgumentParser,
    *,
    baud: int = 9600,
    data_bits: int = 8,
    parity: str = "N",
    stop_bits: int = 1,
) -> None:
    parser.add_argument("--port", help="COM port, for example COM5")
    parser.add_argument("--baud", type=int, default=baud, help=f"baud rate, default {baud}")
    parser.add_argument("--data-bits", type=int, choices=(7, 8), default=data_bits)
    parser.add_argument("--parity", choices=("N", "E", "O", "n", "e", "o"), default=parity)
    parser.add_argument("--stop-bits", type=int, choices=(1, 2), default=stop_bits)
    parser.add_argument("--flow", choices=FLOW_CONTROLS, default="none")
    parser.add_argument("--read-timeout-ms", type=int, default=100)
    parser.add_argument("--write-timeout-ms", type=int, default=1000)


def choose_port(port: str | None) -> str:
    if port:
        return port.strip()
    ports = list_serial_ports()
    print(f"Detected ports: {ports_label(ports)}")
    if ports:
        default = ports[0]
        value = input(f"Port [{default}]: ").strip()
        return (value or default).strip()
    return input("Port: ").strip()


def serial_config_from_args(args: argparse.Namespace) -> SerialConfig:
    return SerialConfig(
        port=choose_port(args.port),
        baudrate=args.baud,
        data_bits=args.data_bits,
        parity=args.parity,
        stop_bits=args.stop_bits,
        flow_control=args.flow,
        read_timeout_ms=args.read_timeout_ms,
        write_timeout_ms=args.write_timeout_ms,
    ).normalized()


def format_hex(data: bytes) -> str:
    return " ".join(f"{byte:02X}" for byte in data)


def print_frame(prefix: str, data: bytes, *, encoding: str = "utf-8") -> None:
    text = data.decode(encoding, errors="replace")
    print(f"{prefix} TEXT: {text!r}")
    print(f"{prefix} HEX : {format_hex(data)}")
