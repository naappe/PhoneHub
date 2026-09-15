import os
import json
import uuid
from datetime import datetime
from pathlib import Path
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

BASE_DIR = Path("C:/PhoneHub")
DATA_DIR = BASE_DIR / "data"
UPLOAD_DIR = BASE_DIR / "iphone_uploads"
PAIR_FILE = DATA_DIR / "iphone_pairs.json"
TOKEN_FILE = DATA_DIR / "companion_token.txt"

DATA_DIR.mkdir(exist_ok=True)
UPLOAD_DIR.mkdir(exist_ok=True)

if TOKEN_FILE.exists():
    TOKEN = TOKEN_FILE.read_text(encoding="utf-8").strip()
else:
    TOKEN = uuid.uuid4().hex[:16]
    TOKEN_FILE.write_text(TOKEN, encoding="utf-8")


def load_pairs():
    if PAIR_FILE.exists():
        try:
            return json.loads(PAIR_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_pairs(data):
    PAIR_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def html_page(auto_ok=False):
    paired_msg = ""
    if auto_ok:
        paired_msg = "<div class='ok'>Auto paired successfully. You can now use PhoneHub.</div>"

    return f"""<!doctype html>
<html>
<head>
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>PhoneHub Companion</title>
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
.ok {{
    background: #064e3b;
    border: 1px solid #10b981;
    color: #d1fae5;
    padding: 12px;
    border-radius: 12px;
    margin-top: 12px;
}}
</style>
</head>
<body>
<div class="wrap">
    <div class="card">
        <h1>PhoneHub Companion</h1>
        <p class="small">Connected to your PhoneHub PC.</p>
        {paired_msg}
                <div class="ok">
            ✅ Phone connected to PhoneHub.<br><br>
            <b>Android:</b> Tap Chrome menu ⋮ → Add to Home screen → Add.<br><br>
            <b>iPhone:</b> Tap Share → Add to Home Screen → Add.<br><br>
            After that, open PhoneHub from your phone home screen.
        </div>
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
        parsed = urlparse(self.path)
        qs = parse_qs(parsed.query)

        if parsed.path == "/":
            auto_ok = False

            if qs.get("token", [""])[0] == TOKEN:
                device_name = qs.get("name", ["Phone"])[0] or "Phone"
                pairs = load_pairs()
                pairs[device_name] = {
                    "paired_at": datetime.now().isoformat(),
                    "last_seen": datetime.now().isoformat(),
                    "auto_paired": True
                }
                save_pairs(pairs)

                success_file = DATA_DIR / "companion_success.txt"
                success_file.write_text(datetime.now().isoformat(), encoding="utf-8")

                auto_ok = True

            self.send_text(html_page(auto_ok=auto_ok))

        elif parsed.path == "/status":
            self.send_text(json.dumps({
                "ok": True,
                "service": "PhoneHub Companion",
                "time": datetime.now().isoformat()
            }), "application/json")
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)

        if self.path == "/note":
            data = parse_qs(body.decode("utf-8", errors="ignore"))
            note = data.get("note", [""])[0]
            note_file = DATA_DIR / "iphone_notes.txt"
            with note_file.open("a", encoding="utf-8") as f:
                f.write(f"\n[{datetime.now().isoformat()}]\n{note}\n")
            self.send_text("<h1>Note saved on PC</h1><a href='/'>Back</a>")

        elif self.path == "/upload":
            filename = f"upload_{datetime.now().strftime('%Y%m%d_%H%M%S')}.bin"
            out = UPLOAD_DIR / filename
            out.write_bytes(body)
            self.send_text(f"<h1>Upload received</h1><p>Saved as {filename}</p><a href='/'>Back</a>")

        else:
            self.send_response(404)
            self.end_headers()


if __name__ == "__main__":
    print("PhoneHub Companion running")
    print("Open on PC: http://127.0.0.1:8088")
    print("Token:", TOKEN)
    ThreadingHTTPServer(("0.0.0.0", 8088), Handler).serve_forever()


