"""Local HTTP interface to the same serialized backend used by terminal clients."""
import json
from pathlib import Path
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from .client import Bridge, catalogue


class Manager:
    def __init__(self, executable):
        self.executable = executable
        self.catalogue = catalogue(executable)
        self.lock = threading.RLock()
        self.bridge = None

    def connect(self, config):
        with self.lock:
            if self.bridge:
                raise ValueError("Disconnect the current device before opening another")
            self.bridge = Bridge(self.executable, config)
            return self.bridge.meta

    def close(self):
        with self.lock:
            if self.bridge:
                self.bridge.close()
                self.bridge = None

    def request(self, action, channel, values):
        with self.lock:
            if not self.bridge:
                raise ValueError("No device is connected")
            return self.bridge.request(action, channel, values)


def create_server(executable, host="127.0.0.1", port=8080):
    manager = Manager(executable)
    static = Path(__file__).parent / "static"

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def send(self, status, value, content_type="application/json; charset=utf-8"):
            data = json.dumps(value, allow_nan=False).encode() if content_type.startswith("application/json") else value
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            try:
                self.wfile.write(data)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def do_GET(self):
            path = urlparse(self.path).path
            if path == "/api/models":
                return self.send(200, manager.catalogue)
            if path == "/api/meta":
                with manager.lock:
                    return self.send(200, manager.bridge.meta if manager.bridge else None)
            files = {"/": ("index.html", "text/html; charset=utf-8"),
                     "/app.js": ("app.js", "text/javascript; charset=utf-8"),
                     "/app.css": ("app.css", "text/css; charset=utf-8")}
            if path not in files:
                return self.send(404, {"error": "Not found"})
            name, content_type = files[path]
            return self.send(200, (static / name).read_bytes(), content_type)

        def do_POST(self):
            try:
                origin = self.headers.get("Origin")
                if origin and urlparse(origin).netloc != self.headers.get("Host"):
                    return self.send(403, {"error": "Cross-origin commands are not allowed"})
                size = int(self.headers.get("Content-Length", "0"))
                if size <= 0 or size > 65536:
                    return self.send(400, {"error": "Invalid request size"})
                def reject_constant(_):
                    raise ValueError("Non-finite JSON value")
                payload = json.loads(self.rfile.read(size), parse_constant=reject_constant)
                if not isinstance(payload, dict):
                    raise ValueError("Expected an object")
                if self.path == "/api/connect":
                    result = manager.connect(payload)
                elif self.path == "/api/disconnect":
                    manager.close()
                    result = None
                elif self.path == "/api/request":
                    result = manager.request(payload.get("action"), payload.get("channel", ""), payload.get("values", []))
                else:
                    return self.send(404, {"error": "Not found"})
                self.send(200, {"ok": True, "data": result})
            except (OSError, ValueError, RuntimeError, TimeoutError) as error:
                self.send(400, {"ok": False, "error": str(error)})

    server = ThreadingHTTPServer((host, port), Handler)
    server.manager = manager
    return server
