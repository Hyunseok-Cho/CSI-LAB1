import unittest

from csi_lab1.modbus_ascii import (
    COMMAND_READ_TEXT,
    COMMAND_WRITE_TEXT,
    ModbusAsciiError,
    decode_frame,
    encode_exception,
    encode_frame,
    lrc,
)


class ModbusAsciiTests(unittest.TestCase):
    def test_lrc(self):
        payload = bytes([0x01, COMMAND_WRITE_TEXT]) + b"Hi"
        self.assertEqual(lrc(payload), (-sum(payload)) & 0xFF)

    def test_encode_decode_round_trip(self):
        wire = encode_frame(1, COMMAND_WRITE_TEXT, b"Hello")
        frame = decode_frame(wire)
        self.assertEqual(frame.address, 1)
        self.assertEqual(frame.command, COMMAND_WRITE_TEXT)
        self.assertEqual(frame.data, b"Hello")

    def test_read_command(self):
        wire = encode_frame(7, COMMAND_READ_TEXT)
        frame = decode_frame(wire)
        self.assertEqual(frame.address, 7)
        self.assertEqual(frame.command, COMMAND_READ_TEXT)
        self.assertEqual(frame.data, b"")

    def test_bad_lrc_is_rejected(self):
        wire = encode_frame(1, COMMAND_WRITE_TEXT, b"Hello")
        corrupted = wire[:-4] + b"00\r\n"
        with self.assertRaises(ModbusAsciiError):
            decode_frame(corrupted)

    def test_exception_response(self):
        wire = encode_exception(1, COMMAND_READ_TEXT, 1)
        frame = decode_frame(wire)
        self.assertEqual(frame.address, 1)
        self.assertTrue(frame.is_exception)
        self.assertEqual(frame.data, b"\x01")


if __name__ == "__main__":
    unittest.main()
