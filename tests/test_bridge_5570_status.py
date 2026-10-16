import importlib.util
import pathlib
import socket
import threading
import unittest

FILE = pathlib.Path(__file__).resolve().parents[1] / "tools" / "bridge-5570-status.py"
spec = importlib.util.spec_from_file_location("bridge_status", FILE)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class BridgeStatusTests(unittest.TestCase):
    def send_message(self, payload):
        a, b = socket.socketpair()
        messages = []
        thread = threading.Thread(target=mod.collect_status, args=(a, threading.Event(), messages.append))
        thread.start()
        b.sendall(payload)
        b.shutdown(socket.SHUT_WR)
        thread.join(2)
        b.close()
        a.close()
        self.assertFalse(thread.is_alive())
        return messages

    def test_handshake_heartbeat_filters_id(self):
        messages = self.send_message(
            b"ANDROIDBRIDGE\nDEVICE_ID=secret\nSTATUS=ONLINE\nBATTERY=62\nREADY=COMMANDS\n---\n"
        )
        self.assertEqual(messages[0]["fields"], {
            "STATUS": "ONLINE", "BATTERY": "62", "READY": "COMMANDS"
        })
        self.assertFalse(messages[0]["verified"])

    def test_rejects_unrecognized_hello(self):
        self.assertEqual(self.send_message(b"HELLO\n")[0]["reason"], "unexpected_protocol")

    def test_rejects_oversize_line(self):
        self.assertEqual(
            self.send_message(b"ANDROIDBRIDGE\n" + b"A" * 2000 + b"\n")[0]["reason"],
            "oversize_line"
        )


if __name__ == "__main__":
    unittest.main()
