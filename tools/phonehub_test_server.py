from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs
import socket

PORT = 8765
BASE = Path(__file__).resolve().parent
RECEIVED = BASE / "received"
RECEIVED.mkdir(exist_ok=True)

class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print("[%s] %s" % (self.client_address[0], fmt % args))

    def send_text(self, code, text):
        data = text.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if urlparse(self.path).path == "/ping":
            return self.send_text(200, "PHONEHUB-PC-ONLINE")
        return self.send_text(404, "Not found")

    def do_POST(self):
        u = urlparse(self.path)
        if u.path != "/upload":
            return self.send_text(404, "Not found")

        n = int(self.headers.get("Content-Length", "0"))
        if n > 64 * 1024:
            return self.send_text(413, "Test file too large")

        name = Path(parse_qs(u.query).get("name", ["phone-test.txt"])[0]).name
        data = self.rfile.read(n)
        out = RECEIVED / name
        out.write_bytes(data)
        return self.send_text(200, f"Saved to {out}")

print("PhoneHub PC transport test")
print(f"Listening on port {PORT} on all PC interfaces, including Tailscale.")
print("Keep this window open while testing from the phone.")
print(f"Received files will be stored in: {RECEIVED}")
print()
ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
