from __future__ import annotations

import argparse
import queue
import secrets
import sys
import threading
import time
import tkinter as tk
from queue import Empty
from tkinter import messagebox, ttk

from .common.cli_common import format_hex
from .common.gui_common import LogPane, SerialConfigPanel
from .common.modbus_ascii import (
    COMMAND_READ_TEXT,
    COMMAND_WRITE_TEXT,
    EX_ILLEGAL_FUNCTION,
    ModbusAsciiError,
    bytes_to_text,
    decode_frame,
    encode_exception,
    encode_frame,
    format_wire_hex,
    validate_address,
)
from .serial_backend import SerialPort
from .task1_terminal import PING_RE, PONG_RE, TERMINATORS, parse_custom_terminator


class Lab1Gui:
    def __init__(self, root: tk.Tk, *, default_port: str | None = None):
        self.root = root
        self.root.title("CSI Lab 1 - RS-232 and MODBUS-ASCII")
        self.root.minsize(1020, 760)

        self.port: SerialPort | None = None
        self.stop_event = threading.Event()
        self.ui_events: queue.Queue[tuple[str, object]] = queue.Queue()
        self.master_responses: queue.Queue[tuple[bytes, object]] = queue.Queue()
        self.write_lock = threading.Lock()
        self.transaction_lock = threading.Lock()

        self.raw_rx_buffer = bytearray()
        self.pending_pings: dict[str, int] = {}
        self.seen_pings: set[str] = set()

        self.modbus_buffer = bytearray()
        self.modbus_last_byte_at: float | None = None
        self.modbus_char_timeout_value = 0.2
        self.modbus_role_value = "master"
        self.slave_address_value = 1
        self.slave_response_text = "Hello from slave"

        self.config_panel = SerialConfigPanel(
            root,
            default_port=default_port,
            default_baud=9600,
            default_data_bits=7,
            default_parity="E",
            default_stop_bits=1,
        )
        self.config_panel.grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 6))

        controls = ttk.Frame(root)
        controls.grid(row=1, column=0, sticky="ew", padx=10, pady=4)
        self.open_button = ttk.Button(controls, text="Open COM", command=self.open_port)
        self.close_button = ttk.Button(controls, text="Close COM", command=self.close_port, state="disabled")
        self.status_var = tk.StringVar(value="Closed")
        self.open_button.grid(row=0, column=0, padx=4)
        self.close_button.grid(row=0, column=1, padx=4)
        ttk.Label(controls, textvariable=self.status_var).grid(row=0, column=2, sticky="w", padx=12)
        controls.columnconfigure(2, weight=1)

        self.notebook = ttk.Notebook(root)
        self.notebook.grid(row=2, column=0, sticky="nsew", padx=10, pady=(6, 10))
        self.task1_tab = ttk.Frame(self.notebook)
        self.task2_tab = ttk.Frame(self.notebook)
        self.notebook.add(self.task1_tab, text="Task 1 - COM terminal")
        self.notebook.add(self.task2_tab, text="Task 2 - MODBUS ASCII")
        self.build_task1_tab()
        self.build_task2_tab()

        root.columnconfigure(0, weight=1)
        root.rowconfigure(2, weight=1)
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        root.after(50, self.process_ui_events)

    def build_task1_tab(self) -> None:
        options = ttk.LabelFrame(self.task1_tab, text="Terminal controls")
        options.grid(row=0, column=0, sticky="ew", padx=8, pady=8)
        self.terminator_var = tk.StringVar(value="crlf")
        self.custom_terminator_var = tk.StringVar(value="")
        ttk.Label(options, text="Terminator").grid(row=0, column=0, sticky="w", padx=4, pady=4)
        ttk.Combobox(
            options,
            textvariable=self.terminator_var,
            values=("none", "cr", "lf", "crlf", "custom"),
            width=10,
        ).grid(row=0, column=1, sticky="w", padx=4)
        ttk.Label(options, text="Custom").grid(row=0, column=2, sticky="w", padx=4)
        ttk.Entry(options, textvariable=self.custom_terminator_var, width=8).grid(row=0, column=3, sticky="w", padx=4)
        ttk.Button(options, text="Ping", command=self.task1_ping).grid(row=0, column=4, padx=4)
        ttk.Button(options, text="Status", command=self.task1_status).grid(row=0, column=5, padx=4)
        ttk.Button(options, text="DTR ON", command=lambda: self.set_dtr(True)).grid(row=0, column=6, padx=4)
        ttk.Button(options, text="DTR OFF", command=lambda: self.set_dtr(False)).grid(row=0, column=7, padx=4)
        ttk.Button(options, text="RTS ON", command=lambda: self.set_rts(True)).grid(row=0, column=8, padx=4)
        ttk.Button(options, text="RTS OFF", command=lambda: self.set_rts(False)).grid(row=0, column=9, padx=4)

        send = ttk.LabelFrame(self.task1_tab, text="Transmit")
        send.grid(row=1, column=0, sticky="ew", padx=8, pady=8)
        self.task1_tx = tk.Text(send, height=4, wrap="word")
        self.task1_tx.grid(row=0, column=0, sticky="ew", padx=6, pady=6)
        ttk.Button(send, text="Send", command=self.task1_send_text).grid(row=0, column=1, sticky="ns", padx=6, pady=6)
        send.columnconfigure(0, weight=1)

        log_frame = ttk.LabelFrame(self.task1_tab, text="Task 1 TX/RX log")
        log_frame.grid(row=2, column=0, sticky="nsew", padx=8, pady=8)
        self.task1_log = LogPane(log_frame, height=20)
        self.task1_log.grid(row=0, column=0, sticky="nsew", padx=6, pady=6)
        ttk.Button(log_frame, text="Clear log", command=self.task1_log.clear).grid(row=1, column=0, sticky="e", padx=6, pady=(0, 6))
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)
        self.task1_tab.columnconfigure(0, weight=1)
        self.task1_tab.rowconfigure(2, weight=1)

    def build_task2_tab(self) -> None:
        settings = ttk.LabelFrame(self.task2_tab, text="MODBUS mode")
        settings.grid(row=0, column=0, sticky="ew", padx=8, pady=8)
        self.modbus_role_var = tk.StringVar(value="master")
        self.modbus_role_var.trace_add("write", lambda *_: self.update_modbus_role())
        self.modbus_char_timeout_var = tk.StringVar(value="0.2")
        ttk.Label(settings, text="Role").grid(row=0, column=0, sticky="w", padx=6, pady=6)
        self.modbus_role_combo = ttk.Combobox(settings, textvariable=self.modbus_role_var, values=("master", "slave"), width=10)
        self.modbus_role_combo.grid(row=0, column=1, sticky="w")
        ttk.Label(settings, text="Inter-character timeout").grid(row=0, column=2, sticky="w", padx=6)
        ttk.Entry(settings, textvariable=self.modbus_char_timeout_var, width=8).grid(row=0, column=3, sticky="w")

        master = ttk.LabelFrame(self.task2_tab, text="Master controls")
        master.grid(row=1, column=0, sticky="ew", padx=8, pady=8)
        self.master_address_var = tk.StringVar(value="1")
        self.master_text_var = tk.StringVar(value="Hello slave")
        self.master_timeout_var = tk.StringVar(value="2.0")
        self.master_retries_var = tk.StringVar(value="1")
        ttk.Label(master, text="Slave address").grid(row=0, column=0, sticky="w", padx=6, pady=6)
        ttk.Spinbox(master, from_=1, to=247, textvariable=self.master_address_var, width=8).grid(row=0, column=1, sticky="w")
        ttk.Label(master, text="Text").grid(row=0, column=2, sticky="w", padx=6)
        ttk.Entry(master, textvariable=self.master_text_var).grid(row=0, column=3, sticky="ew", padx=6)
        ttk.Button(master, text="Write command 1", command=self.modbus_master_write).grid(row=0, column=4, padx=4)
        ttk.Button(master, text="Broadcast command 1", command=self.modbus_master_broadcast).grid(row=0, column=5, padx=4)
        ttk.Button(master, text="Read command 2", command=self.modbus_master_read).grid(row=0, column=6, padx=4)
        ttk.Label(master, text="Timeout").grid(row=1, column=0, sticky="w", padx=6, pady=6)
        ttk.Entry(master, textvariable=self.master_timeout_var, width=8).grid(row=1, column=1, sticky="w")
        ttk.Label(master, text="Retries").grid(row=1, column=2, sticky="w", padx=6)
        ttk.Entry(master, textvariable=self.master_retries_var, width=8).grid(row=1, column=3, sticky="w")
        master.columnconfigure(3, weight=1)

        slave = ttk.LabelFrame(self.task2_tab, text="Slave controls")
        slave.grid(row=2, column=0, sticky="ew", padx=8, pady=8)
        self.slave_address_var = tk.StringVar(value="1")
        self.slave_response_var = tk.StringVar(value=self.slave_response_text)
        self.slave_received_var = tk.StringVar(value="")
        ttk.Label(slave, text="Slave address").grid(row=0, column=0, sticky="w", padx=6, pady=6)
        ttk.Spinbox(slave, from_=1, to=247, textvariable=self.slave_address_var, width=8).grid(row=0, column=1, sticky="w")
        ttk.Label(slave, text="Text returned by command 2").grid(row=0, column=2, sticky="w", padx=6)
        ttk.Entry(slave, textvariable=self.slave_response_var).grid(row=0, column=3, sticky="ew", padx=6)
        ttk.Button(slave, text="Apply slave settings", command=self.apply_slave_settings).grid(row=0, column=4, padx=4)
        ttk.Label(slave, text="Text received by command 1").grid(row=1, column=0, sticky="w", padx=6, pady=6)
        ttk.Label(slave, textvariable=self.slave_received_var).grid(row=1, column=1, columnspan=4, sticky="ew", padx=6)
        slave.columnconfigure(3, weight=1)

        log_frame = ttk.LabelFrame(self.task2_tab, text="Task 2 MODBUS frame log")
        log_frame.grid(row=3, column=0, sticky="nsew", padx=8, pady=8)
        self.task2_log = LogPane(log_frame, height=18)
        self.task2_log.grid(row=0, column=0, sticky="nsew", padx=6, pady=6)
        ttk.Button(log_frame, text="Clear log", command=self.task2_log.clear).grid(row=1, column=0, sticky="e", padx=6, pady=(0, 6))
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)
        self.task2_tab.columnconfigure(0, weight=1)
        self.task2_tab.rowconfigure(3, weight=1)

    def open_port(self) -> None:
        try:
            config = self.config_panel.config()
            port = SerialPort(config)
            port.open()
        except Exception as exc:
            messagebox.showerror("Open failed", str(exc))
            return
        self.apply_modbus_char_timeout(show_error=False)
        self.update_modbus_role()
        self.port = port
        self.stop_event.clear()
        self.config_panel.set_enabled(False)
        self.open_button.configure(state="disabled")
        self.close_button.configure(state="normal")
        self.status_var.set(f"Open: {config.label}")
        self.log_task1(f"[OPEN] {config.label}")
        self.log_task2(f"[OPEN] {config.label}")
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
        self.log_task1("[CLOSE]")
        self.log_task2("[CLOSE]")

    def reader_loop(self) -> None:
        while not self.stop_event.is_set():
            port = self.port
            if port is None:
                return
            try:
                data = port.read(256)
            except Exception as exc:
                if not self.stop_event.is_set():
                    self.ui_events.put(("task1_log", f"[ERROR] {exc}"))
                    self.ui_events.put(("task2_log", f"[ERROR] {exc}"))
                return
            if data:
                self.ui_events.put(("raw_rx", data))
                self.feed_modbus_bytes(data)

    def feed_modbus_bytes(self, data: bytes) -> None:
        char_timeout = self.modbus_char_timeout_value
        for byte in data:
            now = time.monotonic()
            if (
                self.modbus_buffer
                and char_timeout > 0
                and self.modbus_last_byte_at is not None
                and now - self.modbus_last_byte_at > char_timeout
            ):
                self.modbus_buffer.clear()
            self.modbus_last_byte_at = now

            if not self.modbus_buffer:
                if byte == ord(":"):
                    self.modbus_buffer.append(byte)
                continue

            self.modbus_buffer.append(byte)
            if len(self.modbus_buffer) > 1024:
                self.modbus_buffer.clear()
                continue
            if self.modbus_buffer.endswith(b"\r\n"):
                wire = bytes(self.modbus_buffer)
                self.modbus_buffer.clear()
                self.handle_modbus_wire(wire)

    def handle_modbus_wire(self, wire: bytes) -> None:
        self.ui_events.put(("task2_log", f"[RX] {wire!r}"))
        self.ui_events.put(("task2_log", f"[RX HEX] {format_wire_hex(wire)}"))
        try:
            frame = decode_frame(wire)
        except ModbusAsciiError as exc:
            self.ui_events.put(("task2_log", f"[INVALID] {exc}"))
            return

        if self.modbus_role_value == "master":
            self.master_responses.put((wire, frame))
            return
        self.handle_slave_frame(frame)

    def handle_slave_frame(self, frame: object) -> None:
        address = getattr(frame, "address")
        command = getattr(frame, "command")
        data = getattr(frame, "data")
        if address not in (self.slave_address_value, 0):
            self.ui_events.put(("task2_log", f"[IGNORED] frame for address {address}"))
            return
        is_broadcast = address == 0
        if command == COMMAND_WRITE_TEXT:
            text = bytes_to_text(data)
            self.ui_events.put(("slave_received", text))
            self.ui_events.put(("task2_log", f"[COMMAND 1 WRITE_TEXT] {text!r}"))
            if not is_broadcast:
                self.write_modbus(encode_frame(self.slave_address_value, COMMAND_WRITE_TEXT, b"OK"))
        elif command == COMMAND_READ_TEXT:
            if is_broadcast:
                self.ui_events.put(("task2_log", "[BROADCAST READ] ignored; no response"))
            else:
                payload = self.slave_response_text.encode("utf-8")
                self.ui_events.put(("task2_log", f"[COMMAND 2 READ_TEXT] response={self.slave_response_text!r}"))
                self.write_modbus(encode_frame(self.slave_address_value, COMMAND_READ_TEXT, payload))
        else:
            self.ui_events.put(("task2_log", f"[UNSUPPORTED] command {command}"))
            if not is_broadcast:
                self.write_modbus(encode_exception(self.slave_address_value, command, EX_ILLEGAL_FUNCTION))

    def current_terminator(self) -> bytes:
        if self.terminator_var.get() == "custom":
            return parse_custom_terminator(self.custom_terminator_var.get())
        return TERMINATORS[self.terminator_var.get()]

    def task1_send_text(self) -> None:
        text = self.task1_tx.get("1.0", "end-1c")
        try:
            payload = text.encode("utf-8") + self.current_terminator()
        except Exception as exc:
            messagebox.showerror("Terminator error", str(exc))
            return
        self.write_raw(payload, "TX")

    def task1_ping(self) -> None:
        token = secrets.token_hex(4)
        now = time.perf_counter_ns()
        self.pending_pings[token] = now
        payload = f"CSI_PING:{token}:{now}".encode("ascii") + self.current_terminator()
        self.write_raw(payload, "PING")

    def task1_status(self) -> None:
        if self.port is None:
            messagebox.showwarning("Port closed", "Open a COM port first.")
            return
        try:
            status = self.port.modem_status()
        except Exception as exc:
            messagebox.showerror("Status failed", str(exc))
            return
        self.log_task1("[STATUS] " + " ".join(f"{k}={'ON' if v else 'OFF'}" for k, v in status.items()))

    def set_dtr(self, active: bool) -> None:
        if self.port is None:
            messagebox.showwarning("Port closed", "Open a COM port first.")
            return
        self.port.set_dtr(active)
        self.log_task1(f"[DTR] {'ON' if active else 'OFF'}")

    def set_rts(self, active: bool) -> None:
        if self.port is None:
            messagebox.showwarning("Port closed", "Open a COM port first.")
            return
        self.port.set_rts(active)
        self.log_task1(f"[RTS] {'ON' if active else 'OFF'}")

    def write_raw(self, payload: bytes, label: str) -> None:
        if self.port is None:
            messagebox.showwarning("Port closed", "Open a COM port first.")
            return
        try:
            with self.write_lock:
                self.port.write(payload)
        except Exception as exc:
            messagebox.showerror("Write failed", str(exc))
            return
        self.log_task1(f"[{label}] {payload!r}")
        self.log_task1(f"[{label} HEX] {format_hex(payload)}")

    def handle_task1_rx(self, data: bytes) -> None:
        self.raw_rx_buffer.extend(data)
        if len(self.raw_rx_buffer) > 8192:
            del self.raw_rx_buffer[:4096]
        self.log_task1(f"[RX] {data.decode('utf-8', errors='replace')!r}")
        self.log_task1(f"[RX HEX] {format_hex(data)}")
        text = self.raw_rx_buffer.decode("utf-8", errors="ignore")
        for match in PING_RE.finditer(text):
            token, sent_ns = match.groups()
            if token in self.seen_pings:
                continue
            self.seen_pings.add(token)
            payload = f"CSI_PONG:{token}:{sent_ns}".encode("ascii") + self.current_terminator()
            self.write_raw(payload, "AUTO PONG")
        for match in PONG_RE.finditer(text):
            token, _ = match.groups()
            start_ns = self.pending_pings.pop(token, None)
            if start_ns is not None:
                rtt_ms = (time.perf_counter_ns() - start_ns) / 1_000_000
                self.log_task1(f"[PING RTT] {token}: {rtt_ms:.2f} ms")

    def apply_slave_settings(self) -> None:
        try:
            address = int(self.slave_address_var.get())
            if not 1 <= address <= 247:
                raise ValueError("address must be 1..247")
        except Exception as exc:
            messagebox.showerror("Invalid slave settings", str(exc))
            return
        self.slave_address_value = address
        self.slave_response_text = self.slave_response_var.get()
        self.log_task2(f"[SLAVE SETTINGS] address={address}, response={self.slave_response_text!r}")

    def apply_modbus_char_timeout(self, *, show_error: bool = True) -> bool:
        try:
            value = float(self.modbus_char_timeout_var.get())
            if not 0 <= value <= 1:
                raise ValueError("inter-character timeout must be 0..1 seconds")
        except Exception as exc:
            if show_error:
                messagebox.showerror("Invalid MODBUS settings", str(exc))
            return False
        self.modbus_char_timeout_value = value
        return True

    def update_modbus_role(self) -> None:
        self.modbus_role_value = self.modbus_role_var.get()

    def modbus_master_write(self) -> None:
        self.start_master_transaction(COMMAND_WRITE_TEXT, self.master_text_var.get().encode("utf-8"), broadcast=False)

    def modbus_master_broadcast(self) -> None:
        self.start_master_transaction(COMMAND_WRITE_TEXT, self.master_text_var.get().encode("utf-8"), broadcast=True)

    def modbus_master_read(self) -> None:
        self.start_master_transaction(COMMAND_READ_TEXT, b"", broadcast=False)

    def start_master_transaction(self, command: int, data: bytes, *, broadcast: bool) -> None:
        if self.port is None:
            messagebox.showwarning("Port closed", "Open a COM port first.")
            return
        self.update_modbus_role()
        if self.modbus_role_value != "master":
            messagebox.showwarning("Wrong role", "Set Task 2 role to master first.")
            return
        try:
            address = 0 if broadcast else int(self.master_address_var.get())
            validate_address(address)
            timeout = float(self.master_timeout_var.get())
            retries = int(self.master_retries_var.get())
            char_timeout = float(self.modbus_char_timeout_var.get())
            if not 0 <= timeout <= 10:
                raise ValueError("timeout must be 0..10 seconds")
            if not 0 <= retries <= 5:
                raise ValueError("retries must be 0..5")
            if not 0 <= char_timeout <= 1:
                raise ValueError("inter-character timeout must be 0..1 seconds")
        except Exception as exc:
            messagebox.showerror("Invalid transaction settings", str(exc))
            return
        self.modbus_char_timeout_value = char_timeout
        threading.Thread(
            target=self.master_transaction,
            args=(address, command, data, timeout, retries),
            daemon=True,
        ).start()

    def master_transaction(self, address: int, command: int, data: bytes, timeout: float, retries: int) -> None:
        if not self.transaction_lock.acquire(blocking=False):
            self.ui_events.put(("task2_log", "[MASTER] transaction already running"))
            return
        try:
            while True:
                try:
                    self.master_responses.get_nowait()
                except Empty:
                    break
            wire = encode_frame(address, command, data)
            for attempt in range(retries + 1):
                self.ui_events.put(("task2_log", f"[TX attempt {attempt + 1}] {wire!r}"))
                self.ui_events.put(("task2_log", f"[TX HEX] {format_wire_hex(wire)}"))
                self.write_modbus(wire, already_logged=True)
                if address == 0:
                    self.ui_events.put(("task2_log", "[BROADCAST] sent; no response expected"))
                    return
                deadline = time.monotonic() + timeout
                while time.monotonic() < deadline and not self.stop_event.is_set():
                    try:
                        response_wire, response = self.master_responses.get(timeout=0.05)
                    except Empty:
                        continue
                    if getattr(response, "address") != address:
                        self.ui_events.put(("task2_log", f"[RX IGNORED] address {getattr(response, 'address')}"))
                        continue
                    if getattr(response, "command") & 0x80:
                        payload = getattr(response, "data")
                        code = payload[0] if payload else 0
                        self.ui_events.put(("task2_log", f"[EXCEPTION] command={getattr(response, 'command'):02X}, code={code}"))
                        return
                    if getattr(response, "command") != command:
                        self.ui_events.put(("task2_log", f"[RX IGNORED] command {getattr(response, 'command')}"))
                        continue
                    payload = getattr(response, "data")
                    if command == COMMAND_WRITE_TEXT:
                        self.ui_events.put(("task2_log", f"[WRITE ACK] {bytes_to_text(payload)}"))
                    elif command == COMMAND_READ_TEXT:
                        self.ui_events.put(("task2_log", f"[READ TEXT] {bytes_to_text(payload)}"))
                    return
                self.ui_events.put(("task2_log", "[RX] timeout"))
            self.ui_events.put(("task2_log", "[MASTER] transaction failed after retries"))
        finally:
            self.transaction_lock.release()

    def write_modbus(self, wire: bytes, *, already_logged: bool = False) -> None:
        port = self.port
        if port is None:
            return
        with self.write_lock:
            port.write(wire)
        if not already_logged:
            self.ui_events.put(("task2_log", f"[TX] {wire!r}"))
            self.ui_events.put(("task2_log", f"[TX HEX] {format_wire_hex(wire)}"))

    def process_ui_events(self) -> None:
        try:
            while True:
                kind, payload = self.ui_events.get_nowait()
                if kind == "raw_rx":
                    self.handle_task1_rx(payload if isinstance(payload, bytes) else bytes(payload))
                elif kind == "task1_log":
                    self.log_task1(str(payload))
                elif kind == "task2_log":
                    self.log_task2(str(payload))
                elif kind == "slave_received":
                    self.slave_received_var.set(str(payload))
        except Empty:
            pass
        self.root.after(50, self.process_ui_events)

    def log_task1(self, message: str) -> None:
        self.task1_log.append(message)

    def log_task2(self, message: str) -> None:
        self.task2_log.append(message)

    def on_close(self) -> None:
        self.close_port()
        self.root.destroy()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Unified CSI Lab 1 GUI")
    parser.add_argument("--port", help="initial COM port, for example COM5")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = tk.Tk()
    Lab1Gui(root, default_port=args.port)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
