from __future__ import annotations

from dataclasses import dataclass


FLOW_CONTROLS = ("none", "dsrdtr", "rtscts", "xonxoff")
PARITIES = ("N", "E", "O")


@dataclass(frozen=True)
class SerialConfig:
    port: str
    baudrate: int = 9600
    data_bits: int = 8
    parity: str = "N"
    stop_bits: int = 1
    flow_control: str = "none"
    read_timeout_ms: int = 100
    write_timeout_ms: int = 1000

    def normalized(self) -> "SerialConfig":
        parity = self.parity.upper()
        flow_control = self.flow_control.lower()
        if self.data_bits not in (7, 8):
            raise ValueError("data_bits must be 7 or 8")
        if parity not in PARITIES:
            raise ValueError("parity must be one of N, E, O")
        if self.stop_bits not in (1, 2):
            raise ValueError("stop_bits must be 1 or 2")
        if flow_control not in FLOW_CONTROLS:
            raise ValueError(f"flow_control must be one of {', '.join(FLOW_CONTROLS)}")
        if self.baudrate <= 0:
            raise ValueError("baudrate must be positive")
        if self.read_timeout_ms < 0 or self.write_timeout_ms < 0:
            raise ValueError("timeouts must not be negative")
        return SerialConfig(
            port=self.port.strip().upper(),
            baudrate=self.baudrate,
            data_bits=self.data_bits,
            parity=parity,
            stop_bits=self.stop_bits,
            flow_control=flow_control,
            read_timeout_ms=self.read_timeout_ms,
            write_timeout_ms=self.write_timeout_ms,
        )

    @property
    def label(self) -> str:
        return (
            f"{self.port} {self.baudrate} "
            f"{self.data_bits}{self.parity}{self.stop_bits} flow={self.flow_control}"
        )
