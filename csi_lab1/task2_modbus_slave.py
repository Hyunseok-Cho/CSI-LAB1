from __future__ import annotations

import argparse
import sys
import threading

from .cli_common import add_serial_args, serial_config_from_args
from .modbus_ascii import (
    COMMAND_READ_TEXT,
    COMMAND_WRITE_TEXT,
    EX_ILLEGAL_FUNCTION,
    ModbusAsciiError,
    bytes_to_text,
    decode_frame,
    encode_exception,
    encode_frame,
    format_wire_hex,
    read_ascii_frame,
)
from .serial_win32 import SerialPort


class SlaveApp:
    def __init__(self, port: SerialPort, address: int, char_timeout_s: float, encoding: str, response_text: str):
        if not 1 <= address <= 247:
            raise ValueError("slave address must be in range 1..247")
        self.port = port
        self.address = address
        self.char_timeout_s = char_timeout_s
        self.encoding = encoding
        self.response_text = response_text
        self.received_text = ""
        self.stop_event = threading.Event()
        self.lock = threading.Lock()

    def start(self) -> threading.Thread:
        thread = threading.Thread(target=self._receive_loop, daemon=True)
        thread.start()
        return thread

    def _receive_loop(self) -> None:
        while not self.stop_event.is_set():
            wire = read_ascii_frame(self.port, inter_char_timeout_s=self.char_timeout_s)
            if wire is None:
                continue
            print()
            print(f"RX     : {wire!r}")
            print(f"RX HEX : {format_wire_hex(wire)}")
            try:
                frame = decode_frame(wire)
            except ModbusAsciiError as exc:
                print(f"Invalid frame ignored: {exc}")
                print("slave> ", end="", flush=True)
                continue

            if frame.address not in (self.address, 0):
                print(f"Ignored frame for address {frame.address}")
                print("slave> ", end="", flush=True)
                continue

            is_broadcast = frame.address == 0
            if frame.command == COMMAND_WRITE_TEXT:
                text = bytes_to_text(frame.data, self.encoding)
                with self.lock:
                    self.received_text = text
                print(f"Command 1 WRITE_TEXT received: {text!r}")
                if not is_broadcast:
                    self._send(encode_frame(self.address, COMMAND_WRITE_TEXT, b"OK"))
            elif frame.command == COMMAND_READ_TEXT:
                if is_broadcast:
                    print("Broadcast READ_TEXT ignored; no response is sent.")
                else:
                    with self.lock:
                        data = self.response_text.encode(self.encoding)
                    print(f"Command 2 READ_TEXT response: {self.response_text!r}")
                    self._send(encode_frame(self.address, COMMAND_READ_TEXT, data))
            else:
                print(f"Unsupported command {frame.command}")
                if not is_broadcast:
                    self._send(encode_exception(self.address, frame.command, EX_ILLEGAL_FUNCTION))

            print("slave> ", end="", flush=True)

    def _send(self, wire: bytes) -> None:
        self.port.write(wire)
        print(f"TX     : {wire!r}")
        print(f"TX HEX : {format_wire_hex(wire)}")

    def set_response_text(self, text: str) -> None:
        with self.lock:
            self.response_text = text

    def print_status(self) -> None:
        with self.lock:
            print(f"Slave address: {self.address}")
            print(f"Text received from master: {self.received_text!r}")
            print(f"Text returned by command 2: {self.response_text!r}")


def print_help() -> None:
    print(
        "Commands:\n"
        "  /text <text>       set the text returned by command 2\n"
        "  /status            show slave state\n"
        "  /help              show this help\n"
        "  /quit              close the port and exit"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Task 2 MODBUS-ASCII slave")
    add_serial_args(parser, baud=9600, data_bits=7, parity="E", stop_bits=1)
    parser.add_argument("--address", type=int, default=1, help="slave address, 1..247")
    parser.add_argument("--char-timeout", type=float, default=0.2, help="inter-character timeout in seconds")
    parser.add_argument("--encoding", default="utf-8")
    parser.add_argument("--text", default="Hello from slave", help="text returned by command 2")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not 0 <= args.char_timeout <= 1:
        raise ValueError("--char-timeout must be in range 0..1")
    config = serial_config_from_args(args)

    with SerialPort(config) as port:
        app = SlaveApp(port, args.address, args.char_timeout, args.encoding, args.text)
        app.start()
        print(f"Opened MODBUS slave {args.address} on {config.label}")
        print_help()
        while True:
            try:
                line = input("slave> ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break
            if not line:
                continue
            if line == "/quit":
                break
            if line == "/help":
                print_help()
            elif line == "/status":
                app.print_status()
            elif line.startswith("/text "):
                text = line.split(maxsplit=1)[1]
                app.set_response_text(text)
                print(f"Response text set to {text!r}")
            else:
                print("Unknown command. Type /help.")
        app.stop_event.set()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
