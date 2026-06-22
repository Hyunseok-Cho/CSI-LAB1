from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from tkinter.scrolledtext import ScrolledText

from .serial_config import FLOW_CONTROLS, SerialConfig
from ..serial_backend import list_serial_ports


class LogPane(ttk.Frame):
    def __init__(self, master: tk.Misc, *, height: int = 18):
        super().__init__(master)
        self.text = ScrolledText(self, height=height, wrap="word", state="disabled")
        self.text.grid(row=0, column=0, sticky="nsew")
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

    def append(self, message: str) -> None:
        self.text.configure(state="normal")
        self.text.insert("end", message.rstrip() + "\n")
        self.text.see("end")
        self.text.configure(state="disabled")

    def clear(self) -> None:
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        self.text.configure(state="disabled")


class SerialConfigPanel(ttk.LabelFrame):
    def __init__(
        self,
        master: tk.Misc,
        *,
        default_port: str | None = None,
        default_baud: int = 9600,
        default_data_bits: int = 8,
        default_parity: str = "N",
        default_stop_bits: int = 1,
    ):
        super().__init__(master, text="Serial configuration")
        self.port_var = tk.StringVar(value=default_port or "")
        self.baud_var = tk.StringVar(value=str(default_baud))
        self.data_bits_var = tk.StringVar(value=str(default_data_bits))
        self.parity_var = tk.StringVar(value=default_parity)
        self.stop_bits_var = tk.StringVar(value=str(default_stop_bits))
        self.flow_var = tk.StringVar(value="none")

        self.port_combo = ttk.Combobox(self, textvariable=self.port_var, width=10)
        self.baud_combo = ttk.Combobox(
            self,
            textvariable=self.baud_var,
            values=("150", "300", "600", "1200", "2400", "4800", "9600", "19200", "38400", "57600", "115200"),
            width=9,
        )
        self.data_combo = ttk.Combobox(self, textvariable=self.data_bits_var, values=("7", "8"), width=4)
        self.parity_combo = ttk.Combobox(self, textvariable=self.parity_var, values=("N", "E", "O"), width=4)
        self.stop_combo = ttk.Combobox(self, textvariable=self.stop_bits_var, values=("1", "2"), width=4)
        self.flow_combo = ttk.Combobox(self, textvariable=self.flow_var, values=FLOW_CONTROLS, width=10)
        self.refresh_button = ttk.Button(self, text="Refresh", command=self.refresh_ports)

        labels = ("Port", "Baud", "Data", "Parity", "Stop", "Flow")
        widgets = (
            self.port_combo,
            self.baud_combo,
            self.data_combo,
            self.parity_combo,
            self.stop_combo,
            self.flow_combo,
        )
        for column, label in enumerate(labels):
            ttk.Label(self, text=label).grid(row=0, column=column, sticky="w", padx=4, pady=(4, 0))
            widgets[column].grid(row=1, column=column, sticky="ew", padx=4, pady=(0, 4))
        self.refresh_button.grid(row=1, column=len(labels), sticky="ew", padx=4, pady=(0, 4))

        for column in range(len(labels) + 1):
            self.columnconfigure(column, weight=1)
        self.refresh_ports()

    def refresh_ports(self) -> None:
        ports = list_serial_ports()
        self.port_combo.configure(values=ports)
        if not self.port_var.get() and ports:
            self.port_var.set(ports[0])

    def config(self) -> SerialConfig:
        return SerialConfig(
            port=self.port_var.get(),
            baudrate=int(self.baud_var.get()),
            data_bits=int(self.data_bits_var.get()),
            parity=self.parity_var.get(),
            stop_bits=int(self.stop_bits_var.get()),
            flow_control=self.flow_var.get(),
        ).normalized()

    def set_enabled(self, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        for widget in (
            self.port_combo,
            self.baud_combo,
            self.data_combo,
            self.parity_combo,
            self.stop_combo,
            self.flow_combo,
            self.refresh_button,
        ):
            widget.configure(state=state)
