import unittest

from app import core_runtime


class CoreRuntimeTests(unittest.TestCase):
    def test_accepts_valid_tailscale_ipv4(self):
        self.assertEqual(
            core_runtime.normalize_tailscale_ipv4("100.70.94.21"),
            "100.70.94.21",
        )
        self.assertEqual(
            core_runtime.normalize_tailscale_ipv4("100.64.0.1"),
            "100.64.0.1",
        )
        self.assertEqual(
            core_runtime.normalize_tailscale_ipv4("100.127.255.254"),
            "100.127.255.254",
        )

    def test_rejects_non_tailscale_or_invalid_values(self):
        for value in (
            "",
            None,
            "abc",
            "100.70",
            "10.0.0.1",
            "100.128.0.1",
            "100.200.1.1",
            "256.1.1.1",
        ):
            with self.subTest(value=value):
                self.assertEqual(core_runtime.normalize_tailscale_ipv4(value), "")

    def test_normalize_strips_whitespace(self):
        self.assertEqual(
            core_runtime.normalize_tailscale_ipv4(" 100.99.209.74 "),
            "100.99.209.74",
        )


if __name__ == "__main__":
    unittest.main()
