from __future__ import annotations

from .serial_win32 import list_serial_ports, ports_label


def main() -> int:
    ports = list_serial_ports()
    print(f"Detected ports: {ports_label(ports)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
