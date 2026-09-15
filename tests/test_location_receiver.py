import json
import tempfile
import unittest
from pathlib import Path

from app.location_receiver import save_location_record, latest_location_record


class LocationReceiverTests(unittest.TestCase):
    def test_save_location_record_creates_csv_and_latest_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            saved = save_location_record(data_dir, "oneplus-nord-n20-se", "4.17521", "73.50916", "15.5", "test")
            self.assertEqual(saved["latitude"], 4.17521)
            self.assertEqual(saved["longitude"], 73.50916)
            self.assertTrue((data_dir / "location_log.csv").exists())
            self.assertTrue((data_dir / "latest_location.json").exists())
            latest = json.loads((data_dir / "latest_location.json").read_text(encoding="utf-8"))
            self.assertEqual(latest["device"], "oneplus-nord-n20-se")

    def test_latest_location_record_missing_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(latest_location_record(Path(tmp)), {})


if __name__ == "__main__":
    unittest.main()
