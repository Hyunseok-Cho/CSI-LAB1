import unittest

from csi_lab1.common.serial_config import SerialConfig


class SerialConfigTests(unittest.TestCase):
    def test_windows_com_port_is_normalized_to_uppercase(self):
        config = SerialConfig(port="com5").normalized()
        self.assertEqual(config.port, "COM5")

    def test_posix_device_path_keeps_case(self):
        path = "/dev/cu.usbserial-ABC123"
        config = SerialConfig(port=path).normalized()
        self.assertEqual(config.port, path)


if __name__ == "__main__":
    unittest.main()
