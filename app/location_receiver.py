import csv
import json
from datetime import datetime
from pathlib import Path
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

BASE_DIR = Path("C:/PhoneHub")
DATA_DIR = BASE_DIR / "runtime" / "data"
CSV_FILE = DATA_DIR / "location_log.csv"
LATEST_FILE = DATA_DIR / "latest_location.json"


def _to_float(value, default=0.0):
    try:
        return float(str(value).strip())
    except Exception:
        return default


def save_location_record(data_dir, device, lat, lon, accuracy, source="android-companion"):
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)

    record = {
        "time": datetime.now().isoformat(timespec="seconds"),
        "device": (device or "Android Phone").strip(),
        "latitude": _to_float(lat),
        "longitude": _to_float(lon),
        "accuracy_meters": _to_float(accuracy),
        "source": source,
    }

    csv_file = data_dir / "location_log.csv"
    new_file = not csv_file.exists()

    with csv_file.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["time", "device", "latitude", "longitude", "accuracy_meters", "source"],
        )
        if new_file:
            writer.writeheader()
        writer.writerow(record)

    (data_dir / "latest_location.json").write_text(
        json.dumps(record, indent=2),
        encoding="utf-8",
    )
    return record


def latest_location_record(data_dir=DATA_DIR):
    latest_file = Path(data_dir) / "latest_location.json"
    if not latest_file.exists():
        return {}
    try:
        return json.loads(latest_file.read_text(encoding="utf-8"))
    except Exception:
        return {}


class LocationHandler(BaseHTTPRequestHandler):
    def _send(self, code, text, content_type="text/plain"):
        data = text.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", content_type + "; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/status":
            self._send(200, json.dumps({"ok": True, "service": "PhoneHub Location Receiver"}), "application/json")
            return
        if path == "/latest":
            self._send(200, json.dumps(latest_location_record(), indent=2), "application/json")
            return
        self._send(200, "PhoneHub Location Receiver is running")

    def do_POST(self):
        path = urlparse(self.path).path
        if path != "/location":
            self._send(404, "Not found")
            return

        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode("utf-8", errors="ignore")
        data = parse_qs(body)

        record = save_location_record(
            data_dir=DATA_DIR,
            device=data.get("device", [""])[0],
            lat=data.get("lat", [""])[0],
            lon=data.get("lon", [""])[0],
            accuracy=data.get("accuracy", [""])[0],
            source=data.get("source", ["android-companion"])[0],
        )

        self._send(200, json.dumps({"ok": True, "saved": record}), "application/json")

    def log_message(self, format, *args):
        return


def run_server(host="0.0.0.0", port=8787):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    print("PhoneHub Location Receiver running")
    print(f"Listening: http://{host}:{port}")
    print(f"Saving: {CSV_FILE}")
    ThreadingHTTPServer((host, port), LocationHandler).serve_forever()


if __name__ == "__main__":
    run_server()
