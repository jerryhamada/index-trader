"""Local dashboard server.

Serves the dashboard on localhost and keeps it current: every few hours it
downloads the latest bars, reruns the scan and the one-year check, and saves
the result so a restart comes back instantly.

    python server.py          # http://127.0.0.1:8787
    PORT=9000 python server.py
"""
import json
import os
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from report import compute, detail, fetch_all
from scan import RESULTS

ROOT = Path(__file__).parent
PORT = int(os.environ.get("PORT", 8787))
REFRESH_HOURS = 3
RETRY_MINUTES = 10  # after a failed refresh
STATE_FILE = RESULTS / "state.json"

state = {"data": None, "refreshing": False, "last_attempt": 0.0, "error": None}
wake = threading.Event()


def refresh() -> None:
    state["refreshing"] = True
    try:
        failed = fetch_all()
        data = compute()  # falls back to the cache when a download failed
        STATE_FILE.write_text(json.dumps(data))
        state["data"] = data
        state["error"] = "Download failed, showing cached data. " + failed[0] if failed else None
    except Exception as e:
        traceback.print_exc()
        state["error"] = f"{type(e).__name__}: {e}"
    finally:
        state["refreshing"] = False
        state["last_attempt"] = time.time()


def refresh_loop() -> None:
    """Refresh on a wall-clock schedule, so a Mac that slept catches up when it wakes."""
    while True:
        wait = RETRY_MINUTES * 60 if state["error"] else REFRESH_HOURS * 3600
        if wake.is_set() or time.time() - state["last_attempt"] >= wait:
            wake.clear()
            refresh()
        wake.wait(30)


class Handler(BaseHTTPRequestHandler):
    def send(self, body: bytes, content_type: str, status: int = 200) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def send_json(self, obj, status: int = 200) -> None:
        self.send(json.dumps(obj).encode(), "application/json", status)

    def do_GET(self) -> None:
        url = urlparse(self.path)
        if url.path == "/":
            self.send((ROOT / "dashboard.html").read_bytes(), "text/html; charset=utf-8")
        elif url.path == "/api/state":
            self.send_json({
                "data": state["data"],
                "refreshing": state["refreshing"],
                "error": state["error"],
                "refresh_hours": REFRESH_HOURS,
                "now": time.time(),
            })
        elif url.path == "/api/detail":
            try:
                scan_start = state["data"]["year"]["scan_start"] if state["data"] else None
                self.send_json(detail({k: v[0] for k, v in parse_qs(url.query).items()}, scan_start))
            except (KeyError, ValueError, TypeError, FileNotFoundError) as e:
                self.send_json({"error": f"{type(e).__name__}: {e}"}, 400)
        else:
            self.send(b"Not found", "text/plain", 404)

    def do_POST(self) -> None:
        if urlparse(self.path).path == "/api/refresh":
            wake.set()
            self.send_json({"ok": True})
        else:
            self.send(b"Not found", "text/plain", 404)

    def log_message(self, *args) -> None:  # keep the log for errors only
        pass


def main() -> None:
    if STATE_FILE.exists():  # show the last result immediately, then refresh if it is stale
        state["data"] = json.loads(STATE_FILE.read_text())
        state["last_attempt"] = state["data"]["refreshed"]
    threading.Thread(target=refresh_loop, daemon=True).start()
    print(f"Dashboard on http://127.0.0.1:{PORT}", flush=True)
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
