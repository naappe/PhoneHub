import unittest
from phonehub.services.adb_service import parse_devices
class Tests(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(parse_devices("List of devices attached\n100.99.209.74:5555\tdevice\n"),{"100.99.209.74:5555":"device"})
if __name__=="__main__": unittest.main()
