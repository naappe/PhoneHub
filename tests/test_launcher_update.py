from pathlib import Path
import unittest


class PhoneHubLauncherUpdateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.launcher = Path("PhoneHub.bat").read_text(encoding="utf-8").lower()

    def test_checks_that_phonehub_folder_is_a_git_repository(self):
        self.assertIn("git rev-parse --is-inside-work-tree", self.launcher)

    def test_skips_update_when_local_changes_exist(self):
        self.assertIn("git status --porcelain", self.launcher)
        self.assertIn("if defined local_changes goto launch_phonehub", self.launcher)

    def test_updates_from_origin_main(self):
        self.assertIn("git fetch origin main", self.launcher)
        self.assertIn("git pull --ff-only origin main", self.launcher)

    def test_launches_v4_core_app(self):
        self.assertIn("phonehubcore.py", self.launcher)
        self.assertIn("python phonehubcore.py", self.launcher)

    def test_writes_startup_logs(self):
        self.assertIn("launcher_error.log", self.launcher)
        self.assertIn("phonehub_stdout.log", self.launcher)


if __name__ == "__main__":
    unittest.main()
