from __future__ import annotations

import os

if os.name == "nt":
    from .windows.serial_win32 import SerialError, SerialPort, list_serial_ports, ports_label
else:
    from .macos.serial_pyserial import SerialError, SerialPort, list_serial_ports, ports_label

__all__ = ["SerialError", "SerialPort", "list_serial_ports", "ports_label"]
