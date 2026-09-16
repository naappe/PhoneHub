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
        self.assertIn("local changes detected", self.launcher)

    def test_updates_from_origin_main(self):
        self.assertIn("git fetch origin main", self.launcher)
        self.assertIn("git pull --ff-only origin main", self.launcher)

    def test_still_launches_phonehub_after_update_problem(self):
        self.assertIn(":launch_phonehub", self.launcher)
        self.assertIn('start "" "c:\\phonehub\\dist\\phonehub.exe"', self.launcher)


if __name__ == "__main__":
    unittest.main()
