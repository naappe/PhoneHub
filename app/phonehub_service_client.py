import base64
import hashlib
import hmac
import json
import secrets
import socket
import time
import uuid
from pathlib import Path

PROTOCOL_VERSION = 1
DEFAULT_SERVICE_PORT = 8765
DEFAULT_TIMEOUT_SECONDS = 5

CONFIG_DIR = Path.home() / ".phone_remote"
SERVICE_CONFIG_FILE = CONFIG_DIR / "phonehub_service.json"


def canonical_json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def canonical_body(pc_id, nonce, timestamp, command_type, payload):
    return canonical_json({
        "nonce": nonce,
        "payload": payload or {},
        "pcId": pc_id,
        "timestamp": int(timestamp),
        "type": command_type,
        "version": PROTOCOL_VERSION,
    })


def sign_request(secret, nonce, body):
    if isinstance(secret, str):
        secret = secret.encode("utf-8")
    message = f"{nonce}\n{body}".encode("utf-8")
    return hmac.new(secret, message, hashlib.sha256).hexdigest()


def load_service_credentials(path=SERVICE_CONFIG_FILE):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        pc_id = str(data.get("pc_id") or "").strip()
        secret_b64 = str(data.get("secret_b64") or "").strip()
        if not pc_id or not secret_b64:
            return None
        return {
            "pc_id": pc_id,
            "secret": base64.b64decode(secret_b64),
        }
    except Exception:
        return None


def save_service_credentials(pc_id, secret, path=SERVICE_CONFIG_FILE):
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(secret, str):
        secret = secret.encode("utf-8")
    data = {
        "pc_id": pc_id,
        "secret_b64": base64.b64encode(secret).decode("ascii"),
    }
    target.write_text(json.dumps(data, indent=2), encoding="utf-8")


def get_or_create_pc_id(path=SERVICE_CONFIG_FILE):
    creds = load_service_credentials(path)
    if creds:
        return creds["pc_id"]
    return f"pc-{uuid.uuid4()}"


class PhoneHubServiceClient:
    def __init__(self, host, port=DEFAULT_SERVICE_PORT, pc_id=None, secret=None, timeout=DEFAULT_TIMEOUT_SECONDS):
        self.host = str(host or "").strip()
        self.port = int(port)
        self.pc_id = pc_id or ""
        self.secret = secret
        self.timeout = timeout

    @classmethod
    def from_saved_credentials(cls, host, path=SERVICE_CONFIG_FILE):
        creds = load_service_credentials(path)
        if not creds:
            return None
        return cls(host=host, pc_id=creds["pc_id"], secret=creds["secret"])

    def ping(self):
        try:
            response = self.send("ping", {})
            return bool(response.get("ok")) and response.get("data", {}).get("reply") == "pong"
        except Exception:
            return False

    def device_status(self):
        response = self.send("device_status", {})
        if not response.get("ok"):
            return {}
        return response.get("data", {}) or {}

    def request_screen(self):
        return self.send("screen_request", {})

    def pair(self, code):
        pc_id = self.pc_id or get_or_create_pc_id()
        request = build_unsigned_pairing_request(pc_id, code)
        response = send_line(self.host, self.port, json.dumps(request, separators=(",", ":")), self.timeout)
        parsed = json.loads(response)
        if not parsed.get("ok"):
            return parsed
        data = parsed.get("data", {})
        secret_b64 = data.get("secret")
        paired_pc_id = data.get("pcId") or pc_id
        if secret_b64:
            secret = base64.b64decode(secret_b64)
            save_service_credentials(paired_pc_id, secret)
            self.pc_id = paired_pc_id
            self.secret = secret
        return parsed

    def send(self, command_type, payload=None):
        if not self.host:
            raise ValueError("PhoneHub service host is required")
        if not self.pc_id or not self.secret:
            raise ValueError("PhoneHub service credentials are missing")
        request = build_signed_request(self.pc_id, self.secret, command_type, payload or {})
        response = send_line(self.host, self.port, json.dumps(request, separators=(",", ":")), self.timeout)
        return json.loads(response)


def build_signed_request(pc_id, secret, command_type, payload):
    nonce = secrets.token_hex(16)
    timestamp = int(time.time() * 1000)
    body = canonical_body(pc_id, nonce, timestamp, command_type, payload)
    return {
        "version": PROTOCOL_VERSION,
        "pcId": pc_id,
        "nonce": nonce,
        "timestamp": timestamp,
        "type": command_type,
        "payload": payload,
        "signature": sign_request(secret, nonce, body),
    }


def build_unsigned_pairing_request(pc_id, code):
    return {
        "version": PROTOCOL_VERSION,
        "pcId": pc_id,
        "nonce": secrets.token_hex(16),
        "timestamp": int(time.time() * 1000),
        "type": "pair",
        "payload": {"code": str(code).strip()},
        "signature": "",
    }


def send_line(host, port, line, timeout=DEFAULT_TIMEOUT_SECONDS):
    with socket.create_connection((host, int(port)), timeout=timeout) as sock:
        sock.settimeout(timeout)
        sock.sendall(line.encode("utf-8") + b"\n")
        data = b""
        while not data.endswith(b"\n"):
            chunk = sock.recv(4096)
            if not chunk:
                break
            data += chunk
    return data.decode("utf-8").strip()
