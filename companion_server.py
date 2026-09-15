import os
import json
import uuid
from datetime import datetime
from pathlib import Path
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import parse_qs

BASE_DIR = Path("C:/PhoneHub")
DATA_DIR = BASE_DIR / "data"
UPLOAD_DIR = BASE_DIR / "iphone_uploads"
PAIR_FILE = DATA_DIR / "iphone_pairs.json"

DATA_DIR.mkdir(exist_ok=True)
UPLOAD_DIR.mkdir(exist_ok=True)

PAIR_CODE = str(uuid.uuid4())[:6].upper()

def load_pairs():
    if PAIR_FILE.exists():
        try:
            return json.loads(PAIR_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}

def save_pairs(data):
    PAIR_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")

def html_page():
    return f"""<!doctype html>
<html>
<head>
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>PhoneHub iPhone Companion</title>
<style>
body {{
    margin: 0;
    font-family: Arial, sans-serif;
    background: #0f172a;
    color: white;
}}
.wrap {{
    max-width: 520px;
    margin: auto;
    padding: 24px;
}}
.card {{
    background: #111827;
    border: 1px solid #334155;
    border-radius: 18px;
    padding: 20px;
    margin-bottom: 16px;
}}
h1 {{
    font-size: 26px;
    margin: 0 0 8px;
}}
input, textarea, button {{
    width: 100%;
    box-sizing: border-box;
    padding: 14px;
    border-radius: 12px;
    border: 1px solid #475569;
    margin-top: 10px;
    font-size: 16px;
}}
button {{
    background: #f59e0b;
    color: #111827;
    font-weight: bold;
    border: none;
}}
.small {{
    color: #cbd5e1;
    font-size: 14px;
}}
.code {{
    font-size: 28px;
    font-weight: bold;
    color: #fbbf24;
    letter-spacing: 4px;
}}
</style>
</head>
<body>
<div class="wrap">
    <div class="card">
        <h1>PhoneHub iPhone Companion</h1>
        <p class="small">Your iPhone can connect to your own PhoneHub backend.</p>
        <p>Pair code:</p>
        <div class="code">{PAIR_CODE}</div>
    </div>

    <div class="card">
        <h2>Pair iPhone</h2>
        <form method="POST" action="/pair">
            <input name="device_name" placeholder="iPhone name" required>
            <input name="pair_code" placeholder="Pair code" required>
            <button>Pair</button>
        </form>
    </div>

    <div class="card">
        <h2>Send Note to PC</h2>
        <form method="POST" action="/note">
            <textarea name="note" rows="5" placeholder="Write note here..." required></textarea>
            <button>Send Note</button>
        </form>
    </div>

    <div class="card">
        <h2>Upload Photo / File</h2>
        <form method="POST" action="/upload" enctype="multipart/form-data">
            <input type="file" name="file" required>
            <button>Upload to PC</button>
        </form>
        <p class="small">Files save to C:\\PhoneHub\\iphone_uploads</p>
    </div>
</div>
</body>
</html>"""

class Handler(BaseHTTPRequestHandler):
    def send_text(self, text, content_type="text/html"):
        data = text.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", content_type + "; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/" or self.path.startswith("/?"):
            self.send_text(html_page())
        elif self.path == "/status":
            self.send_text(json.dumps({
                "ok": True,
                "service": "PhoneHub iPhone Companion",
                "time": datetime.now().isoformat()
            }), "application/json")
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)

        if self.path == "/pair":
            data = parse_qs(body.decode("utf-8", errors="ignore"))
            device_name = data.get("device_name", ["iPhone"])[0]
            pair_code = data.get("pair_code", [""])[0].upper().strip()

            if pair_code != PAIR_CODE:
                self.send_text("<h1>Wrong pair code</h1><a href='/'>Back</a>")
                return

            pairs = load_pairs()
            pairs[device_name] = {
                "paired_at": datetime.now().isoformat(),
                "last_seen": datetime.now().isoformat()
            }
            save_pairs(pairs)

            self.send_text("<h1>iPhone paired successfully</h1><a href='/'>Back</a>")

        elif self.path == "/note":
            data = parse_qs(body.decode("utf-8", errors="ignore"))
            note = data.get("note", [""])[0]
            note_file = DATA_DIR / "iphone_notes.txt"
            with note_file.open("a", encoding="utf-8") as f:
                f.write(f"\n[{datetime.now().isoformat()}]\n{note}\n")
            self.send_text("<h1>Note saved on PC</h1><a href='/'>Back</a>")

        elif self.path == "/upload":
            # Simple raw save for first version
            filename = f"upload_{datetime.now().strftime('%Y%m%d_%H%M%S')}.bin"
            out = UPLOAD_DIR / filename
            out.write_bytes(body)
            self.send_text(f"<h1>Upload received</h1><p>Saved as {filename}</p><a href='/'>Back</a>")

        else:
            self.send_response(404)
            self.end_headers()

if __name__ == "__main__":
    print("PhoneHub iPhone Companion running")
    print("Open on PC: http://127.0.0.1:8088")
    print("Open on iPhone through Tailscale/Wi-Fi: http://YOUR-PC-IP:8088")
    print("Pair code:", PAIR_CODE)
    ThreadingHTTPServer(("0.0.0.0", 8088), Handler).serve_forever()
