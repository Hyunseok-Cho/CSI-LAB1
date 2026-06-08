from __future__ import annotations

import argparse
import queue
import sys
import threading
import time
import tkinter as tk
from tkinter import messagebox, ttk

from .gui_common import LogPane, SerialConfigPanel
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
    validate_address,
)
from .serial_win32 import SerialPort


class ModbusGui:
    def __init__(self, root: tk.Tk, *, default_port: str | None = None, default_role: str = "master"):
        self.root = root
        self.root.title("CSI Lab 1 - Task 2 MODBUS-ASCII")
        self.root.minsize(940, 680)

        self.port: SerialPort | None = None
        self.stop_event = threading.Event()
        self.events: queue.Queue[tuple[str, object]] = queue.Queue()
        self.write_lock = threading.Lock()
        self.transaction_lock = threading.Lock()
        self.response_text_value = "Hello from slave"
        self.slave_address_value = 1

        top = ttk.Frame(root)
        top.grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 6))
        self.config_panel = SerialConfigPanel(
            top,
            default_port=default_port,
            default_baud=9600,
            default_data_bits=7,
            default_parity="E",
            default_stop_bits=1,
        )
        self.config_panel.grid(row=0, column=0, sticky="ew")
        role_frame = ttk.LabelFrame(top, text="Role")
        role_frame.grid(row=0, column=1, sticky="ns", padx=(8, 0))
        self.role_var = tk.StringVar(value=default_role)
        self.role_combo = ttk.Combobox(role_frame, textvariable=self.role_var, values=("master", "slave"), width=10)
        self.role_combo.grid(row=0, column=0, padx=8, pady=8)
        top.columnconfigure(0, weight=1)

        control = ttk.Frame(root)
        control.grid(row=1, column=0, sticky="ew", padx=10, pady=4)
        self.open_button = ttk.Button(control, text="Open", command=self.open_port)
        self.close_button = ttk.Button(control, text="Close", command=self.close_port, state="disabled")
        self.status_var = tk.StringVar(value="Closed")
        self.open_button.grid(row=0, column=0, padx=4)
        self.close_button.grid(row=0, column=1, padx=4)
        ttk.Label(control, textvariable=self.status_var).grid(row=0, column=2, sticky="w", padx=12)
        control.columnconfigure(2, weight=1)

        notebook = ttk.Notebook(root)
        notebook.grid(row=2, column=0, sticky="ew", padx=10, pady=6)
        self.master_tab = ttk.Frame(notebook)
        self.slave_tab = ttk.Frame(notebook)
        notebook.add(self.master_tab, text="Master controls")
        notebook.add(self.slave_tab, text="Slave controls")
        self.build_master_tab()
        self.build_slave_tab()

        log_frame = ttk.LabelFrame(root, text="MODBUS frame log")
        log_frame.grid(row=3, column=0, sticky="nsew", padx=10, pady=(6, 10))
        self.log = LogPane(log_frame, height=22)
        self.log.grid(row=0, column=0, sticky="nsew", padx=6, pady=6)
        ttk.Button(log_frame, text="Clear log", command=self.log.clear).grid(row=1, column=0, sticky="e", padx=6, pady=(0, 6))
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)

        root.columnconfigure(0, weight=1)
        root.rowconfigure(3, weight=1)
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        root.after(50, self.process_events)

    def build_master_tab(self) -> None:
        self.master_address_var = tk.StringVar(value="1")
        self.master_text_var = tk.StringVar(value="Hello slave")
        self.timeout_var = tk.StringVar(value="2.0")
        self.retries_var = tk.StringVar(value="1")
        self.char_timeout_var = tk.StringVar(value="0.2")

        ttk.Label(self.master_tab, text="Slave address").grid(row=0, column=0, sticky="w", padx=6, pady=6)
        ttk.Spinbox(self.master_tab, from_=1, to=247, textvariable=self.master_address_var, width=8).grid(row=0, column=1, sticky="w")
        ttk.Label(self.master_tab, text="Text").grid(row=0, column=2, sticky="w", padx=6)
        ttk.Entry(self.master_tab, textvariable=self.master_text_var).grid(row=0, column=3, sticky="ew", padx=6)
        ttk.Button(self.master_tab, text="Write command 1", command=self.master_write).grid(row=0, column=4, padx=4)
        ttk.Button(self.master_tab, text="Broadcast command 1", command=self.master_broadcast).grid(row=0, column=5, padx=4)
        ttk.Button(self.master_tab, text="Read command 2", command=self.master_read).grid(row=0, column=6, padx=4)

        ttk.Label(self.master_tab, text="Timeout").grid(row=1, column=0, sticky="w", padx=6, pady=6)
        ttk.Entry(self.master_tab, textvariable=self.timeout_var, width=8).grid(row=1, column=1, sticky="w")
        ttk.Label(self.master_tab, text="Retries").grid(row=1, column=2, sticky="w", padx=6)
        ttk.Entry(self.master_tab, textvariable=self.retries_var, width=8).grid(row=1, column=3, sticky="w")
        ttk.Label(self.master_tab, text="Char timeout").grid(row=1, column=4, sticky="w", padx=6)
        ttk.Entry(self.master_tab, textvariable=self.char_timeout_var, width=8).grid(row=1, column=5, sticky="w")
        self.master_tab.columnconfigure(3, weight=1)

    def build_slave_tab(self) -> None:
        self.slave_address_var = tk.StringVar(value="1")
        self.slave_response_var = tk.StringVar(value=self.response_text_value)
        self.slave_received_var = tk.StringVar(value="")

        ttk.Label(self.slave_tab, text="Slave address").grid(row=0, column=0, sticky="w", padx=6, pady=6)
        ttk.Spinbox(self.slave_tab, from_=1, to=247, textvariable=self.slave_address_var, width=8).grid(row=0, column=1, sticky="w")
        ttk.Label(self.slave_tab, text="Text returned by command 2").grid(row=0, column=2, sticky="w", padx=6)
        ttk.Entry(self.slave_tab, textvariable=self.slave_response_var).grid(row=0, column=3, sticky="ew", padx=6)
        ttk.Button(self.slave_tab, text="Apply", command=self.apply_slave_settings).grid(row=0, column=4, padx=4)
        ttk.Label(self.slave_tab, text="Text received by command 1").grid(row=1, column=0, sticky="w", padx=6, pady=6)
        ttk.Label(self.slave_tab, textvariable=self.slave_received_var).grid(row=1, column=1, columnspan=4, sticky="ew", padx=6)
        self.slave_tab.columnconfigure(3, weight=1)

    def apply_slave_settings(self) -> None:
        try:
            address = int(self.slave_address_var.get())
            if not 1 <= address <= 247:
                raise ValueError("address must be 1..247")
        except Exception as exc:
            messagebox.showerror("Invalid slave settings", str(exc))
            return
        self.slave_address_value = address
        self.response_text_value = self.slave_response_var.get()
        self.log.append(f"[SLAVE SETTINGS] address={address}, response={self.response_text_value!r}")

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
        self.role_combo.configure(state="disabled")
        self.open_button.configure(state="disabled")
        self.close_button.configure(state="normal")
        self.status_var.set(f"Open: {config.label} role={self.role_var.get()}")
        self.log.append(f"[OPEN] {config.label} role={self.role_var.get()}")
        if self.role_var.get() == "slave":
            self.apply_slave_settings()
            threading.Thread(target=self.slave_loop, daemon=True).start()

    def close_port(self) -> None:
        self.stop_event.set()
        if self.port is not None:
            try:
                self.port.close()
            except Exception:
                pass
        self.port = None
        self.config_panel.set_enabled(True)
        self.role_combo.configure(state="normal")
        self.open_button.configure(state="normal")
        self.close_button.configure(state="disabled")
        self.status_var.set("Closed")
        self.log.append("[CLOSE]")

    def ensure_master_ready(self) -> bool:
        if self.port is None:
            messagebox.showwarning("Port closed", "Open a COM port first.")
            return False
        if self.role_var.get() != "master":
            messagebox.showwarning("Wrong role", "Open this window as master to send master transactions.")
            return False
        return True

    def master_write(self) -> None:
        if not self.ensure_master_ready():
            return
        address = int(self.master_address_var.get())
        data = self.master_text_var.get().encode("utf-8")
        self.start_master_transaction(address, COMMAND_WRITE_TEXT, data)

    def master_broadcast(self) -> None:
        if not self.ensure_master_ready():
            return
        data = self.master_text_var.get().encode("utf-8")
        self.start_master_transaction(0, COMMAND_WRITE_TEXT, data)

    def master_read(self) -> None:
        if not self.ensure_master_ready():
            return
        address = int(self.master_address_var.get())
        self.start_master_transaction(address, COMMAND_READ_TEXT, b"")

    def start_master_transaction(self, address: int, command: int, data: bytes) -> None:
        try:
            validate_address(address)
            timeout = float(self.timeout_var.get())
            retries = int(self.retries_var.get())
            char_timeout = float(self.char_timeout_var.get())
        except Exception as exc:
            messagebox.showerror("Invalid transaction settings", str(exc))
            return
        threading.Thread(
            target=self.master_transaction,
            args=(address, command, data, timeout, retries, char_timeout),
            daemon=True,
        ).start()

    def master_transaction(
        self,
        address: int,
        command: int,
        data: bytes,
        timeout: float,
        retries: int,
        char_timeout: float,
    ) -> None:
        if not self.transaction_lock.acquire(blocking=False):
            self.events.put(("log", "[MASTER] transaction already running"))
            return
        try:
            port = self.port
            if port is None:
                return
            wire = encode_frame(address, command, data)
            for attempt in range(retries + 1):
                self.events.put(("log", f"[TX attempt {attempt + 1}] {wire!r}"))
                self.events.put(("log", f"[TX HEX] {format_wire_hex(wire)}"))
                with self.write_lock:
                    port.write(wire)
                if address == 0:
                    self.events.put(("log", "[BROADCAST] sent; no response expected"))
                    return
                response_wire = read_ascii_frame(
                    port,
                    inter_char_timeout_s=char_timeout,
                    deadline=time.monotonic() + timeout,
                    stop_event=self.stop_event,
                )
                if response_wire is None:
                    self.events.put(("log", "[RX] timeout"))
                    continue
                self.events.put(("log", f"[RX] {response_wire!r}"))
                self.events.put(("log", f"[RX HEX] {format_wire_hex(response_wire)}"))
                try:
                    response = decode_frame(response_wire)
                except ModbusAsciiError as exc:
                    self.events.put(("log", f"[RX INVALID] {exc}"))
                    continue
                if response.address != address:
                    self.events.put(("log", f"[RX IGNORED] address {response.address}"))
                    continue
                if response.command & 0x80:
                    code = response.data[0] if response.data else 0
                    self.events.put(("log", f"[EXCEPTION] command={response.command:02X}, code={code}"))
                    return
                if response.command == COMMAND_WRITE_TEXT:
                    self.events.put(("log", f"[WRITE ACK] {bytes_to_text(response.data)}"))
                    return
                if response.command == COMMAND_READ_TEXT:
                    self.events.put(("log", f"[READ TEXT] {bytes_to_text(response.data)}"))
                    return
            self.events.put(("log", "[MASTER] transaction failed after retries"))
        finally:
            self.transaction_lock.release()

    def slave_loop(self) -> None:
        while not self.stop_event.is_set():
            port = self.port
            if port is None:
                return
            wire = read_ascii_frame(port, inter_char_timeout_s=0.2, stop_event=self.stop_event)
            if wire is None:
                continue
            self.events.put(("log", f"[RX] {wire!r}"))
            self.events.put(("log", f"[RX HEX] {format_wire_hex(wire)}"))
            try:
                frame = decode_frame(wire)
            except ModbusAsciiError as exc:
                self.events.put(("log", f"[INVALID] {exc}"))
                continue
            if frame.address not in (self.slave_address_value, 0):
                self.events.put(("log", f"[IGNORED] frame for address {frame.address}"))
                continue
            is_broadcast = frame.address == 0
            if frame.command == COMMAND_WRITE_TEXT:
                text = bytes_to_text(frame.data)
                self.events.put(("slave_received", text))
                self.events.put(("log", f"[COMMAND 1 WRITE_TEXT] {text!r}"))
                if not is_broadcast:
                    self.slave_send(encode_frame(self.slave_address_value, COMMAND_WRITE_TEXT, b"OK"))
            elif frame.command == COMMAND_READ_TEXT:
                if is_broadcast:
                    self.events.put(("log", "[BROADCAST READ] ignored; no response"))
                else:
                    data = self.response_text_value.encode("utf-8")
                    self.events.put(("log", f"[COMMAND 2 READ_TEXT] response={self.response_text_value!r}"))
                    self.slave_send(encode_frame(self.slave_address_value, COMMAND_READ_TEXT, data))
            else:
                self.events.put(("log", f"[UNSUPPORTED] command {frame.command}"))
                if not is_broadcast:
                    self.slave_send(encode_exception(self.slave_address_value, frame.command, EX_ILLEGAL_FUNCTION))

    def slave_send(self, wire: bytes) -> None:
        port = self.port
        if port is None:
            return
        with self.write_lock:
            port.write(wire)
        self.events.put(("log", f"[TX] {wire!r}"))
        self.events.put(("log", f"[TX HEX] {format_wire_hex(wire)}"))

    def process_events(self) -> None:
        try:
            while True:
                kind, payload = self.events.get_nowait()
                if kind == "log":
                    self.log.append(str(payload))
                elif kind == "slave_received":
                    self.slave_received_var.set(str(payload))
        except queue.Empty:
            pass
        self.root.after(50, self.process_events)

    def on_close(self) -> None:
        self.close_port()
        self.root.destroy()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Task 2 MODBUS-ASCII GUI")
    parser.add_argument("--port", help="initial COM port, for example COM5")
    parser.add_argument("--role", choices=("master", "slave"), default="master")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = tk.Tk()
    ModbusGui(root, default_port=args.port, default_role=args.role)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
