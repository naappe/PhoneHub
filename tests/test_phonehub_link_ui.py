from pathlib import Path
import unittest


class PhoneHubLinkUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = Path("app/PhoneHub.py").read_text(encoding="utf-8-sig")

    def test_phonehub_link_is_primary_branding(self):
        self.assertIn('APP_VERSION = "v2.7-phonehub-link"', self.source)
        self.assertIn('sub = QLabel("PhoneHub Link")', self.source)

    def test_dashboard_exposes_link_actions(self):
        self.assertIn('"PhoneHub Link"', self.source)
        self.assertIn('QPushButton("Open Phone Viewer")', self.source)
        self.assertIn('QPushButton("Install Phone App")', self.source)

    def test_link_actions_use_published_urls(self):
        self.assertIn('PHONEHUB_VIEWER_URL = "https://naappe.github.io/PhoneHub/"', self.source)
        self.assertIn('PHONEHUB_APK_URL = "https://github.com/naappe/PhoneHub/releases/download/phonehub-link-v0.1-test/PhoneHub-Link-v0.1-debug.apk"', self.source)
        self.assertIn('webbrowser.open(PHONEHUB_VIEWER_URL)', self.source)
        self.assertIn('webbrowser.open(PHONEHUB_APK_URL)', self.source)

    def test_startup_does_not_refresh_adb_status(self):
        init_block = self.source.split("    def build_ui(self):", 1)[0]
        self.assertNotIn("self.refresh_status()", init_block)

    def test_legacy_modes_are_clearly_labeled(self):
        self.assertIn('("Legacy Tailscale Setup", self.page_setup_new_phone)', self.source)
        self.assertIn('("Legacy Screen", self.page_screen)', self.source)


if __name__ == "__main__":
    unittest.main()
