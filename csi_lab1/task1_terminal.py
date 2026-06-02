from __future__ import annotations

import argparse
import re
import secrets
import sys
import threading
import time

from .cli_common import add_serial_args, format_hex, print_frame, serial_config_from_args
from .serial_win32 import SerialPort


TERMINATORS = {
    "none": b"",
    "cr": b"\r",
    "lf": b"\n",
    "crlf": b"\r\n",
}

PING_RE = re.compile(r"CSI_PING:([0-9a-f]+):(\d+)")
PONG_RE = re.compile(r"CSI_PONG:([0-9a-f]+):(\d+)")


def parse_custom_terminator(value: str) -> bytes:
    value = value.replace("\\r", "\r").replace("\\n", "\n").replace("\\t", "\t")
    data = value.encode("utf-8")
    if len(data) > 2:
        raise ValueError("custom terminator must be 1 or 2 bytes")
    return data


def terminator_from_args(args: argparse.Namespace) -> bytes:
    if args.terminator == "custom":
        if not args.custom_terminator:
            raise ValueError("--custom-terminator is required when --terminator custom")
        return parse_custom_terminator(args.custom_terminator)
    return TERMINATORS[args.terminator]


class TerminalApp:
    def __init__(self, port: SerialPort, terminator: bytes, encoding: str):
        self.port = port
        self.terminator = terminator
        self.encoding = encoding
        self.stop_event = threading.Event()
        self.pending_pings: dict[str, int] = {}
        self.seen_pings: set[str] = set()
        self.rx_buffer = bytearray()
        self.lock = threading.Lock()

    def start_receiver(self) -> threading.Thread:
        thread = threading.Thread(target=self._receive_loop, daemon=True)
        thread.start()
        return thread

    def _receive_loop(self) -> None:
        while not self.stop_event.is_set():
            data = self.port.read(256)
            if not data:
                continue
            with self.lock:
                self.rx_buffer.extend(data)
                if len(self.rx_buffer) > 8192:
                    del self.rx_buffer[:4096]
            print()
            print_frame("RX", data, encoding=self.encoding)
            self._handle_control_messages()
            print("> ", end="", flush=True)

    def _handle_control_messages(self) -> None:
        with self.lock:
            text = self.rx_buffer.decode(self.encoding, errors="ignore")

        for match in PING_RE.finditer(text):
            token, sent_ns = match.groups()
            if token in self.seen_pings:
                continue
            self.seen_pings.add(token)
            payload = f"CSI_PONG:{token}:{sent_ns}".encode("ascii") + self.terminator
            self.port.write(payload)
            print(f"Auto PONG sent for ping {token}")

        for match in PONG_RE.finditer(text):
            token, _ = match.groups()
            start_ns = self.pending_pings.pop(token, None)
            if start_ns is not None:
                rtt_ms = (time.perf_counter_ns() - start_ns) / 1_000_000
                print(f"PING response {token}: RTT {rtt_ms:.2f} ms")

    def send_text(self, text: str) -> None:
        payload = text.encode(self.encoding) + self.terminator
        self.port.write(payload)
        print_frame("TX", payload, encoding=self.encoding)

    def ping(self) -> None:
        token = secrets.token_hex(4)
        now = time.perf_counter_ns()
        self.pending_pings[token] = now
        payload = f"CSI_PING:{token}:{now}".encode("ascii") + self.terminator
        self.port.write(payload)
        print_frame("PING TX", payload, encoding=self.encoding)

    def print_status(self) -> None:
        status = self.port.modem_status()
        print(" ".join(f"{name}={'ON' if value else 'OFF'}" for name, value in status.items()))


def print_help() -> None:
    print(
        "Commands:\n"
        "  text                 send text plus the selected terminator\n"
        "  /ping                send a ping and measure round-trip delay\n"
        "  /status              show CTS/DSR/RI/DCD modem input states\n"
        "  /dtr on|off          manually set DTR output\n"
        "  /rts on|off          manually set RTS output\n"
        "  /clear               clear RX/TX buffers\n"
        "  /help                show this help\n"
        "  /quit                close the port and exit"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Task 1 RS-232 text terminal and ping tool")
    add_serial_args(parser, baud=9600, data_bits=8, parity="N", stop_bits=1)
    parser.add_argument("--terminator", choices=("none", "cr", "lf", "crlf", "custom"), default="crlf")
    parser.add_argument("--custom-terminator", help=r"custom terminator, supports \r, \n and \t")
    parser.add_argument("--encoding", default="utf-8")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config = serial_config_from_args(args)
    terminator = terminator_from_args(args)

    with SerialPort(config) as port:
        app = TerminalApp(port, terminator, args.encoding)
        app.start_receiver()
        print(f"Opened {config.label}, terminator={args.terminator!r}")
        print_help()
        while True:
            try:
                line = input("> ")
            except (EOFError, KeyboardInterrupt):
                print()
                break
            command = line.strip()
            if command == "/quit":
                break
            if command == "/help":
                print_help()
            elif command == "/ping":
                app.ping()
            elif command == "/status":
                app.print_status()
            elif command == "/clear":
                port.clear()
                print("Buffers cleared")
            elif command.startswith("/dtr "):
                value = command.split(maxsplit=1)[1].lower()
                port.set_dtr(value in ("on", "1", "true"))
                print(f"DTR set to {value}")
            elif command.startswith("/rts "):
                value = command.split(maxsplit=1)[1].lower()
                port.set_rts(value in ("on", "1", "true"))
                print(f"RTS set to {value}")
            elif command.startswith("/"):
                print("Unknown command. Type /help.")
            else:
                app.send_text(line)

        app.stop_event.set()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
