from __future__ import annotations

import argparse
import sys
import time

from .cli_common import add_serial_args, serial_config_from_args
from .modbus_ascii import (
    COMMAND_READ_TEXT,
    COMMAND_WRITE_TEXT,
    ModbusAsciiError,
    bytes_to_text,
    decode_frame,
    encode_frame,
    format_wire_hex,
    read_ascii_frame,
    validate_address,
)
from .serial_win32 import SerialPort


class MasterApp:
    def __init__(self, port: SerialPort, transaction_timeout_s: float, retries: int, char_timeout_s: float):
        self.port = port
        self.transaction_timeout_s = transaction_timeout_s
        self.retries = retries
        self.char_timeout_s = char_timeout_s

    def transact(self, address: int, command: int, data: bytes = b"") -> None:
        validate_address(address)
        wire = encode_frame(address, command, data)
        for attempt in range(self.retries + 1):
            print(f"TX attempt {attempt + 1}: {wire!r}")
            print(f"TX HEX       : {format_wire_hex(wire)}")
            self.port.write(wire)

            if address == 0:
                print("Broadcast sent. MODBUS slaves must not respond to broadcast frames.")
                return

            deadline = time.monotonic() + self.transaction_timeout_s
            response_wire = read_ascii_frame(
                self.port,
                inter_char_timeout_s=self.char_timeout_s,
                deadline=deadline,
            )
            if response_wire is None:
                print("RX timeout")
                continue

            print(f"RX           : {response_wire!r}")
            print(f"RX HEX       : {format_wire_hex(response_wire)}")
            try:
                response = decode_frame(response_wire)
            except ModbusAsciiError as exc:
                print(f"Invalid response: {exc}")
                continue

            if response.address != address:
                print(f"Ignoring response for address {response.address}")
                continue
            if response.command & 0x80:
                code = response.data[0] if response.data else 0
                print(f"Exception response: command={response.command:02X}, code={code}")
                return
            if response.command != command:
                print(f"Unexpected response command {response.command}")
                continue

            if command == COMMAND_WRITE_TEXT:
                print(f"WRITE acknowledged: {bytes_to_text(response.data)}")
            elif command == COMMAND_READ_TEXT:
                print(f"READ text from slave: {bytes_to_text(response.data)}")
            return

        print("Transaction failed after all retries.")


def print_help() -> None:
    print(
        "Commands:\n"
        "  /write <addr> <text>      addressed write-text transaction, command 1\n"
        "  /broadcast <text>         broadcast write-text transaction to address 0\n"
        "  /read <addr>              read slave text, command 2\n"
        "  /help                     show this help\n"
        "  /quit                     close the port and exit"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Task 2 MODBUS-ASCII master")
    add_serial_args(parser, baud=9600, data_bits=7, parity="E", stop_bits=1)
    parser.add_argument("--timeout", type=float, default=2.0, help="transaction timeout in seconds")
    parser.add_argument("--retries", type=int, default=1, help="retransmissions after timeout, 0..5")
    parser.add_argument("--char-timeout", type=float, default=0.2, help="inter-character timeout in seconds")
    parser.add_argument("--encoding", default="utf-8")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not 0 <= args.retries <= 5:
        raise ValueError("--retries must be in range 0..5")
    if not 0 <= args.timeout <= 10:
        raise ValueError("--timeout must be in range 0..10")
    if not 0 <= args.char_timeout <= 1:
        raise ValueError("--char-timeout must be in range 0..1")

    config = serial_config_from_args(args)
    with SerialPort(config) as port:
        app = MasterApp(port, args.timeout, args.retries, args.char_timeout)
        print(f"Opened MODBUS master on {config.label}")
        print_help()
        while True:
            try:
                line = input("master> ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break
            if not line:
                continue
            if line == "/quit":
                break
            if line == "/help":
                print_help()
                continue
            if line.startswith("/write "):
                _, addr_text, text = line.split(maxsplit=2)
                app.transact(int(addr_text), COMMAND_WRITE_TEXT, text.encode(args.encoding))
                continue
            if line.startswith("/broadcast "):
                text = line.split(maxsplit=1)[1]
                app.transact(0, COMMAND_WRITE_TEXT, text.encode(args.encoding))
                continue
            if line.startswith("/read "):
                _, addr_text = line.split(maxsplit=1)
                app.transact(int(addr_text), COMMAND_READ_TEXT)
                continue
            print("Unknown command. Type /help.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
