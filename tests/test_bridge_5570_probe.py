import socket
import threading
import unittest

from pathlib import Path
import importlib.util

FILE = Path(__file__).resolve().parents[1] / "tools" / "bridge-5570-probe.py"
spec = importlib.util.spec_from_file_location("bridge_probe", FILE)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class BridgeProbeTests(unittest.TestCase):
    def test_rejects_invalid_duration(self):
        with self.assertRaises(ValueError):
            module.run_probe(bind_ip="127.0.0.1", expected_ip="127.0.0.1", duration=0)

    def test_rejects_invalid_port(self):
        with self.assertRaises(ValueError):
            module.run_probe(bind_ip="127.0.0.1", expected_ip="127.0.0.1", duration=1, port=0)

    def test_accepts_local_connection_without_reading_payload(self):
        temp = socket.socket()
        temp.bind(("127.0.0.1", 0))
        port = temp.getsockname()[1]
        temp.close()
        lines = []
        results = []
        th = threading.Thread(
            target=lambda: results.append(module.run_probe("127.0.0.1", "127.0.0.1",
                                                            2, port, lines.append)),
            daemon=True)
        th.start()
        for _ in range(15):
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                    break
            except OSError:
                import time
                time.sleep(0.05)
        th.join(timeout=4)
        self.assertFalse(th.is_alive())
        self.assertEqual(results, [1])
        self.assertTrue(any("PHONE_CONNECTION" in line for line in lines))


if __name__ == "__main__":
    unittest.main()
