import importlib
import unittest


class PhoneConfigTests(unittest.TestCase):
    def _module(self):
        try:
            return importlib.import_module("app.phone_config")
        except ModuleNotFoundError:
            self.fail("app.phone_config is missing")

    def test_accepts_valid_tailscale_ipv4(self):
        mod = self._module()
        self.assertTrue(mod.is_valid_tailscale_ipv4("100.70.94.21"))
        self.assertTrue(mod.is_valid_tailscale_ipv4("100.64.0.1"))
        self.assertTrue(mod.is_valid_tailscale_ipv4("100.127.255.254"))

    def test_rejects_non_tailscale_or_invalid_values(self):
        mod = self._module()
        for value in ("", "abc", "100.70", "10.0.0.1", "100.128.0.1", "256.1.1.1"):
            with self.subTest(value=value):
                self.assertFalse(mod.is_valid_tailscale_ipv4(value))

    def test_normalize_returns_empty_for_invalid_and_strips_valid(self):
        mod = self._module()
        self.assertEqual(mod.normalize_tailscale_ipv4(" 100.70.94.21 "), "100.70.94.21")
        self.assertEqual(mod.normalize_tailscale_ipv4("10.0.0.1"), "")
        self.assertEqual(mod.normalize_tailscale_ipv4(None), "")


if __name__ == "__main__":
    unittest.main()
