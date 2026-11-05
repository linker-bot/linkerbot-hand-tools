"""Local HTTP interface to the same serialized backend used by terminal clients."""
import json
from pathlib import Path
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from .client import Bridge, catalogue
from .monitor import Monitor


class Manager:
    def __init__(self, executable):
        self.executable = executable
        self.catalogue = catalogue(executable)
        self.lock = threading.RLock()
        self.bridge = None
        self.monitor = None
        self.connection_id = 0

    def connect(self, config):
        with self.lock:
            if self.bridge and (self.bridge.closed or self.bridge.process.poll() is not None):
                self.close()
            if self.bridge:
                raise ValueError("Disconnect the current device before opening another")
            self.bridge = Bridge(self.executable, config)
            self.connection_id += 1
            self.monitor = Monitor(self.bridge)
            self.monitor.start()
            return self.bridge.meta

    def close(self):
        with self.lock:
            if self.bridge:
                self.monitor.stop()
                self.bridge.close()
                self.monitor.join()
                self.bridge = None
                self.monitor = None

    def request(self, action, channel, values):
        with self.lock:
            if not self.bridge:
                raise ValueError("No device is connected")
            return self.bridge.request(action, channel, values)

    def state(self):
        with self.lock:
            if not self.monitor:
                return {"connected": False, "meta": None, "rates": {}, "samples": {}}
            return {**self.monitor.snapshot(), "connection_id": self.connection_id}

    def set_rates(self, rates):
        with self.lock:
            if not self.monitor or not self.monitor.snapshot()["connected"]:
                raise ValueError("No device is connected")
            return self.monitor.set_rates(rates)


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
            if path == "/api/state":
                return self.send(200, manager.state())
            if path == "/api/meta":
                state = manager.state()
                return self.send(200, state["meta"] if state["connected"] else None)
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
                elif self.path == "/api/rates":
                    result = manager.set_rates(payload)
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
