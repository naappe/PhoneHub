from pathlib import Path
import unittest


class PhoneHubLinkUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.link_source = Path("app/PhoneHubLink.py").read_text(encoding="utf-8-sig")
        cls.launcher = Path("PhoneHub.bat").read_text(encoding="utf-8-sig").lower()

    def test_primary_app_is_phonehub_link(self):
        self.assertIn('APP_VERSION = "v2.7-phonehub-link"', self.link_source)
        self.assertIn('QLabel("PhoneHub Link")', self.link_source)
        self.assertIn('QPushButton("Open Phone Viewer")', self.link_source)
        self.assertIn('QPushButton("Install Phone App")', self.link_source)

    def test_link_actions_use_published_urls(self):
        self.assertIn('PHONEHUB_VIEWER_URL = "https://naappe.github.io/PhoneHub/"', self.link_source)
        self.assertIn('PHONEHUB_APK_URL = "https://github.com/naappe/PhoneHub/releases/download/phonehub-link-v0.1-test/PhoneHub-Link-v0.1-debug.apk"', self.link_source)
        self.assertIn('webbrowser.open(PHONEHUB_VIEWER_URL)', self.link_source)
        self.assertIn('webbrowser.open(PHONEHUB_APK_URL)', self.link_source)

    def test_legacy_app_remains_available_as_fallback(self):
        self.assertIn('QPushButton("Open Legacy PhoneHub")', self.link_source)
        self.assertIn('dist\\phonehub.exe', self.link_source.lower())

    def test_launcher_prefers_link_app_and_falls_back_to_legacy_exe(self):
        self.assertIn('app\\phonehublink.py', self.launcher)
        self.assertIn('pythonw', self.launcher)
        self.assertIn('dist\\phonehub.exe', self.launcher)


if __name__ == "__main__":
    unittest.main()
