from pathlib import Path
import unittest


class PhoneHubTailscaleUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = Path("app/PhoneHubTailscale.py").read_text(encoding="utf-8-sig")
        cls.base_source = Path("app/PhoneHub.py").read_text(encoding="utf-8-sig")
        cls.launcher = Path("PhoneHub.bat").read_text(encoding="utf-8-sig").lower()

    def test_dashboard_has_tailscale_ip_input_and_save_connect(self):
        self.assertIn('self.dashboard_ip_input = QLineEdit()', self.source)
        self.assertIn('self.dashboard_ip_input.setPlaceholderText("Example: 100.70.94.21")', self.source)
        self.assertIn('QPushButton("Save & Connect")', self.source)

    def test_dashboard_loads_saved_ip_and_reuses_existing_connection_logic(self):
        self.assertIn('ip, _ = get_saved_ip()', self.source)
        self.assertIn('self.dashboard_ip_input.setText(ip)', self.source)
        self.assertIn('save_phone_ip(ip, 5555)', self.source)
        self.assertIn('connect_remote_adb()', self.source)

    def test_existing_tools_continue_to_use_saved_tailscale_ip(self):
        self.assertIn('def adb_target():', self.base_source)
        self.assertIn('ip, port = get_saved_ip()', self.base_source)
        self.assertIn('return f"{ip}:{port}" if ip else ""', self.base_source)

    def test_launcher_prefers_tailscale_dashboard_and_falls_back_to_exe(self):
        self.assertIn('app\\phonehubtailscale.py', self.launcher)
        self.assertNotIn('app\\phonehublink.py', self.launcher)
        self.assertIn('dist\\phonehub.exe', self.launcher)


if __name__ == "__main__":
    unittest.main()
