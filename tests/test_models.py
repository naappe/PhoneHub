import unittest

from phonehub.domain.models import ConnectionState, DeviceSnapshot


class DeviceSnapshotTests(unittest.TestCase):
    def test_default_snapshot_is_disconnected(self):
        snapshot = DeviceSnapshot()
        self.assertEqual(snapshot.state, ConnectionState.DISCONNECTED)
        self.assertEqual(snapshot.device_name, "Not connected")


if __name__ == "__main__":
    unittest.main()
