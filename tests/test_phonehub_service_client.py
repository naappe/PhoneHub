import unittest

from app.phonehub_service_client import canonical_body, sign_request


class PhoneHubServiceClientTests(unittest.TestCase):
    def test_signature_is_stable(self):
        secret = b"01234567890123456789012345678901"
        body = canonical_body("pc-1", "nonce-1", 1234567890, "ping", {})
        first = sign_request(secret, "nonce-1", body)
        second = sign_request(secret, "nonce-1", body)
        self.assertEqual(first, second)

    def test_payload_change_changes_signature(self):
        secret = b"01234567890123456789012345678901"
        a = canonical_body("pc-1", "n", 1, "ping", {})
        b = canonical_body("pc-1", "n", 1, "device_status", {})
        self.assertNotEqual(sign_request(secret, "n", a), sign_request(secret, "n", b))

    def test_pairing_request_has_unsigned_signature(self):
        secret = b"01234567890123456789012345678901"
        client_body = canonical_body("pc-1", "n", 1, "pair", {"code": "123456"})
        self.assertIn('"type":"pair"', client_body)
        self.assertEqual(sign_request(secret, "n", client_body), sign_request(secret, "n", client_body))


if __name__ == "__main__":
    unittest.main()
