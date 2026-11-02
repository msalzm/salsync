"""A small local browser interface for Salsync. Run: python src/app.py."""

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile
import threading
import webbrowser


PROJECT_DIR = Path(__file__).resolve().parents[1]
UI_DIR = Path(__file__).with_name("ui")
WORKER = Path(__file__).with_name("app_worker.py")


class AppState:
    def __init__(self):
        self.lock = threading.Lock()
        self.token = secrets.token_urlsafe(32)
        self.process = None
        self.tracks = []
        self.playlists = []
        self.source = "youtube"
        self.job = {"id": 0, "status": "idle", "action": None, "logs": []}

    def snapshot(self):
        with self.lock:
            return {"tracks": self.tracks, "playlists": self.playlists, "source": self.source,
                    "job": {**self.job, "logs": list(self.job["logs"])}}

    def start(self, request):
        with self.lock:
            if self.job["status"] == "running":
                raise ValueError("A task is already running. Wait for it to finish.")
            action = request.get("action")
            if action not in {"playlists", "normalize", "search", "download", "organize"}:
                raise ValueError("Unknown action.")
            if action in {"playlists", "normalize"}:
                if request.get("source") not in {"youtube", "spotify", "folder"}:
                    raise ValueError("Choose a source.")
                if request["source"] == "folder":
                    if action != "normalize" or not isinstance(request.get("folder"), str) or not request["folder"].strip():
                        raise ValueError("Enter a folder path.")
                elif action == "normalize" and not request.get("playlist_id"):
                    raise ValueError("Choose a playlist first.")
            else:
                indices = request.get("indices", [])
                if not isinstance(indices, list) or not indices:
                    raise ValueError("Select at least one track.")
                if any(type(index) is not int or index < 0 or index >= len(self.tracks) for index in indices):
                    raise ValueError("Invalid track selection. Reload the tracks.")
                request = {**request, "tracks": [self.tracks[index] for index in dict.fromkeys(indices)]}
                if action == "organize" and any(track.get("service") != "local" for track in request["tracks"]):
                    raise ValueError("Only local folder tracks can be tagged and renamed.")
                options = request.get("options", {})
                if not isinstance(options, dict) or any(not isinstance(value, str) for value in options.values()):
                    raise ValueError("Settings must be text values.")
            if action == "normalize":
                self.tracks = []
                self.source = request["source"]
            if action == "playlists":
                self.playlists = []
                self.tracks = []
                self.source = request["source"]
            self.job = {"id": self.job["id"] + 1, "status": "running", "action": action, "logs": []}
        threading.Thread(target=self.run, args=(request,), daemon=True).start()

    def run(self, request):
        try:
            with tempfile.TemporaryDirectory(prefix="salsync-") as temporary:
                directory = Path(temporary)
                (directory / "request.json").write_text(json.dumps(request), encoding="utf-8")
                with subprocess.Popen(
                    [sys.executable, "-u", str(WORKER), str(directory)],
                    cwd=PROJECT_DIR, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, encoding="utf-8", errors="replace", start_new_session=True,
                ) as process:
                    with self.lock:
                        self.process = process
                    for line in process.stdout:
                        with self.lock:
                            self.job["logs"].append(line.rstrip())
                            self.job["logs"] = self.job["logs"][-300:]
                    code = process.wait()
                # Organize can partly fail; keep the renames that succeeded.
                result_path = directory / "result.json"
                result = json.loads(result_path.read_text(encoding="utf-8")) if result_path.is_file() else {}
                with self.lock:
                    if "organized" in result:
                        renamed = dict(result["organized"])
                        self.tracks = [renamed.get(track["service_id"], track) for track in self.tracks]
                    if "tracks" in result:
                        self.tracks = result["tracks"]
                    if "playlists" in result:
                        self.playlists = result["playlists"]
                    self.job["status"] = "done" if code == 0 else "error"
        except Exception as error:
            with self.lock:
                self.job["logs"].append(str(error))
                self.job["status"] = "error"
        finally:
            with self.lock:
                self.process = None


def handler_for(state):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def send(self, status, body, content_type="application/json"):
            self.send_response(status)
            self.send_header("Content-Type", content_type + "; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path == "/api/state":
                self.send(200, json.dumps(state.snapshot()).encode())
            elif self.path == "/":
                body = (UI_DIR / "index.html").read_text(encoding="utf-8")
                default_binary = os.environ.get("SOCKSEEK_BINARY", "")
                if not default_binary and (Path.home() / "Downloads" / "sockseek").is_file():
                    default_binary = str(Path.home() / "Downloads" / "sockseek")
                settings = {"binary": default_binary,
                            "config": os.environ.get("SOCKSEEK_CONFIG", str(PROJECT_DIR / ".sockseek.conf") if (PROJECT_DIR / ".sockseek.conf").is_file() else ""),
                            "output_dir": str(PROJECT_DIR / "downloads")}
                body = body.replace("__APP_TOKEN__", state.token).replace("__DEFAULTS__", json.dumps(settings).replace("<", "\\u003c"))
                self.send(200, body.encode(), "text/html")
            elif self.path in {"/app.js", "/style.css"}:
                content_type = "text/javascript" if self.path.endswith(".js") else "text/css"
                self.send(200, (UI_DIR / self.path[1:]).read_bytes(), content_type)
            else:
                self.send(404, b'{"error":"Not found"}')

        def do_POST(self):
            if self.path != "/api/tasks":
                self.send(404, b'{"error":"Not found"}')
                return
            if not secrets.compare_digest(self.headers.get("X-App-Token", ""), state.token):
                self.send(403, b'{"error":"Reload the app and try again."}')
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 65536:
                    raise ValueError("Invalid request size.")
                request = json.loads(self.rfile.read(length))
                if not isinstance(request, dict):
                    raise ValueError("Invalid request.")
                state.start(request)
            except (ValueError, TypeError) as error:
                self.send(400, json.dumps({"error": str(error)}).encode())
                return
            self.send(202, b'{"accepted":true}')
    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    state = AppState()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), handler_for(state))
    url = f"http://127.0.0.1:{server.server_port}"
    print(f"Salsync is running at {url}\nPress Ctrl+C to stop.", flush=True)
    if not args.no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        # Wait for an active task so downloads and tagging can finish safely.
        with state.lock:
            process = state.process
        if process is not None:
            print("Waiting for the current task to finish…", flush=True)
            process.wait()


if __name__ == "__main__":
    main()
