import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PHONEHUB_TAILSCALE = ROOT / "app" / "PhoneHubTailscale.py"


class PhoneHubServiceUiTests(unittest.TestCase):
    def test_dashboard_mentions_phonehub_service_mode(self):
        text = PHONEHUB_TAILSCALE.read_text(encoding="utf-8-sig")
        self.assertIn("PhoneHub Service", text)
        self.assertIn("Android app not paired", text)
        self.assertIn("Use ADB Fallback", text)

    def test_status_prefers_service_before_adb(self):
        text = PHONEHUB_TAILSCALE.read_text(encoding="utf-8-sig")
        service_index = text.index("PhoneHubServiceClient")
        adb_index = text.index("connect_remote_adb")
        self.assertLess(service_index, adb_index)


if __name__ == "__main__":
    unittest.main()
