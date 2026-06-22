from __future__ import annotations

import argparse
import queue
import re
import secrets
import sys
import threading
import time
import tkinter as tk
from tkinter import messagebox, ttk

from .common.cli_common import format_hex
from .common.gui_common import LogPane, SerialConfigPanel
from .serial_backend import SerialError, SerialPort
from .task1_terminal import PING_RE, PONG_RE, TERMINATORS, parse_custom_terminator


class Task1Gui:
    def __init__(self, root: tk.Tk, *, default_port: str | None = None):
        self.root = root
        self.root.title("CSI Lab 1 - Task 1 RS-232 Terminal")
        self.root.minsize(900, 620)

        self.port: SerialPort | None = None
        self.stop_event = threading.Event()
        self.events: queue.Queue[tuple[str, object]] = queue.Queue()
        self.rx_buffer = bytearray()
        self.pending_pings: dict[str, int] = {}
        self.seen_pings: set[str] = set()
        self.write_lock = threading.Lock()

        self.config_panel = SerialConfigPanel(root, default_port=default_port, default_baud=9600, default_data_bits=8)
        self.config_panel.grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 6))

        control = ttk.Frame(root)
        control.grid(row=1, column=0, sticky="ew", padx=10, pady=4)
        self.open_button = ttk.Button(control, text="Open", command=self.open_port)
        self.close_button = ttk.Button(control, text="Close", command=self.close_port, state="disabled")
        self.status_var = tk.StringVar(value="Closed")
        ttk.Label(control, textvariable=self.status_var).grid(row=0, column=2, sticky="w", padx=12)
        self.open_button.grid(row=0, column=0, padx=4)
        self.close_button.grid(row=0, column=1, padx=4)
        control.columnconfigure(2, weight=1)

        options = ttk.LabelFrame(root, text="Task 1 options")
        options.grid(row=2, column=0, sticky="ew", padx=10, pady=6)
        self.terminator_var = tk.StringVar(value="crlf")
        self.custom_terminator_var = tk.StringVar(value="")
        ttk.Label(options, text="Terminator").grid(row=0, column=0, sticky="w", padx=4, pady=4)
        ttk.Combobox(
            options,
            textvariable=self.terminator_var,
            values=("none", "cr", "lf", "crlf", "custom"),
            width=10,
        ).grid(row=0, column=1, sticky="w", padx=4, pady=4)
        ttk.Label(options, text="Custom").grid(row=0, column=2, sticky="w", padx=4, pady=4)
        ttk.Entry(options, textvariable=self.custom_terminator_var, width=8).grid(row=0, column=3, sticky="w", padx=4)
        ttk.Button(options, text="Ping", command=self.send_ping).grid(row=0, column=4, padx=4)
        ttk.Button(options, text="Status", command=self.show_modem_status).grid(row=0, column=5, padx=4)
        ttk.Button(options, text="DTR ON", command=lambda: self.set_dtr(True)).grid(row=0, column=6, padx=4)
        ttk.Button(options, text="DTR OFF", command=lambda: self.set_dtr(False)).grid(row=0, column=7, padx=4)
        ttk.Button(options, text="RTS ON", command=lambda: self.set_rts(True)).grid(row=0, column=8, padx=4)
        ttk.Button(options, text="RTS OFF", command=lambda: self.set_rts(False)).grid(row=0, column=9, padx=4)

        send_frame = ttk.LabelFrame(root, text="Transmit")
        send_frame.grid(row=3, column=0, sticky="ew", padx=10, pady=6)
        self.tx_text = tk.Text(send_frame, height=4, wrap="word")
        self.tx_text.grid(row=0, column=0, sticky="ew", padx=6, pady=6)
        ttk.Button(send_frame, text="Send", command=self.send_text).grid(row=0, column=1, sticky="ns", padx=6, pady=6)
        send_frame.columnconfigure(0, weight=1)

        log_frame = ttk.LabelFrame(root, text="TX/RX log")
        log_frame.grid(row=4, column=0, sticky="nsew", padx=10, pady=(6, 10))
        self.log = LogPane(log_frame, height=20)
        self.log.grid(row=0, column=0, sticky="nsew", padx=6, pady=6)
        ttk.Button(log_frame, text="Clear log", command=self.log.clear).grid(row=1, column=0, sticky="e", padx=6, pady=(0, 6))
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)

        root.columnconfigure(0, weight=1)
        root.rowconfigure(4, weight=1)
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        root.after(50, self.process_events)

    def current_terminator(self) -> bytes:
        if self.terminator_var.get() == "custom":
            return parse_custom_terminator(self.custom_terminator_var.get())
        return TERMINATORS[self.terminator_var.get()]

    def open_port(self) -> None:
        try:
            config = self.config_panel.config()
            port = SerialPort(config)
            port.open()
        except Exception as exc:
            messagebox.showerror("Open failed", str(exc))
            return
        self.port = port
        self.stop_event.clear()
        self.config_panel.set_enabled(False)
        self.open_button.configure(state="disabled")
        self.close_button.configure(state="normal")
        self.status_var.set(f"Open: {config.label}")
        self.log.append(f"[OPEN] {config.label}")
        threading.Thread(target=self.reader_loop, daemon=True).start()

    def close_port(self) -> None:
        self.stop_event.set()
        if self.port is not None:
            try:
                self.port.close()
            except Exception:
                pass
        self.port = None
        self.config_panel.set_enabled(True)
        self.open_button.configure(state="normal")
        self.close_button.configure(state="disabled")
        self.status_var.set("Closed")
        self.log.append("[CLOSE]")

    def reader_loop(self) -> None:
        while not self.stop_event.is_set():
            port = self.port
            if port is None:
                return
            try:
                data = port.read(256)
            except Exception as exc:
                if not self.stop_event.is_set():
                    self.events.put(("error", str(exc)))
                return
            if data:
                self.events.put(("rx", data))

    def write_bytes(self, data: bytes, label: str = "TX") -> None:
        if self.port is None:
            messagebox.showwarning("Port closed", "Open a COM port first.")
            return
        try:
            with self.write_lock:
                self.port.write(data)
        except Exception as exc:
            messagebox.showerror("Write failed", str(exc))
            return
        self.log.append(f"[{label}] {data!r}")
        self.log.append(f"[{label} HEX] {format_hex(data)}")

    def send_text(self) -> None:
        text = self.tx_text.get("1.0", "end-1c")
        try:
            payload = text.encode("utf-8") + self.current_terminator()
        except Exception as exc:
            messagebox.showerror("Terminator error", str(exc))
            return
        self.write_bytes(payload)

    def send_ping(self) -> None:
        token = secrets.token_hex(4)
        now = time.perf_counter_ns()
        self.pending_pings[token] = now
        payload = f"CSI_PING:{token}:{now}".encode("ascii") + self.current_terminator()
        self.write_bytes(payload, "PING")

    def handle_control_messages(self) -> None:
        text = self.rx_buffer.decode("utf-8", errors="ignore")
        for match in PING_RE.finditer(text):
            token, sent_ns = match.groups()
            if token in self.seen_pings:
                continue
            self.seen_pings.add(token)
            payload = f"CSI_PONG:{token}:{sent_ns}".encode("ascii") + self.current_terminator()
            self.write_bytes(payload, "AUTO PONG")

        for match in PONG_RE.finditer(text):
            token, _ = match.groups()
            start_ns = self.pending_pings.pop(token, None)
            if start_ns is not None:
                rtt_ms = (time.perf_counter_ns() - start_ns) / 1_000_000
                self.log.append(f"[PING RTT] {token}: {rtt_ms:.2f} ms")

    def show_modem_status(self) -> None:
        if self.port is None:
            messagebox.showwarning("Port closed", "Open a COM port first.")
            return
        try:
            status = self.port.modem_status()
        except Exception as exc:
            messagebox.showerror("Status failed", str(exc))
            return
        self.log.append("[STATUS] " + " ".join(f"{k}={'ON' if v else 'OFF'}" for k, v in status.items()))

    def set_dtr(self, active: bool) -> None:
        if self.port is None:
            messagebox.showwarning("Port closed", "Open a COM port first.")
            return
        self.port.set_dtr(active)
        self.log.append(f"[DTR] {'ON' if active else 'OFF'}")

    def set_rts(self, active: bool) -> None:
        if self.port is None:
            messagebox.showwarning("Port closed", "Open a COM port first.")
            return
        self.port.set_rts(active)
        self.log.append(f"[RTS] {'ON' if active else 'OFF'}")

    def process_events(self) -> None:
        try:
            while True:
                kind, payload = self.events.get_nowait()
                if kind == "rx":
                    data = payload if isinstance(payload, bytes) else bytes(payload)
                    self.rx_buffer.extend(data)
                    if len(self.rx_buffer) > 8192:
                        del self.rx_buffer[:4096]
                    self.log.append(f"[RX] {data.decode('utf-8', errors='replace')!r}")
                    self.log.append(f"[RX HEX] {format_hex(data)}")
                    self.handle_control_messages()
                elif kind == "error":
                    self.log.append(f"[ERROR] {payload}")
        except queue.Empty:
            pass
        self.root.after(50, self.process_events)

    def on_close(self) -> None:
        self.close_port()
        self.root.destroy()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Task 1 RS-232 terminal GUI")
    parser.add_argument("--port", help="initial COM port, for example COM5")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = tk.Tk()
    Task1Gui(root, default_port=args.port)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
