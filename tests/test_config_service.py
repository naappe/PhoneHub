import unittest
from phonehub.services.config_service import normalize_tailscale_ipv4
class Tests(unittest.TestCase):
    def test_range(self):
        self.assertEqual(normalize_tailscale_ipv4("100.99.209.74"),"100.99.209.74")
        self.assertEqual(normalize_tailscale_ipv4("10.0.0.1"),"")
if __name__=="__main__": unittest.main()
