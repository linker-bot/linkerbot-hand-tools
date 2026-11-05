"""Serialized process boundary shared by CLI, terminal and HTTP clients."""
import collections
import json
import math
import os
from pathlib import Path
import queue
import shutil
import subprocess
import threading

PREFIX = "HAND_TOOLS "


def default_bridge():
    if os.environ.get("HAND_TOOLS_BRIDGE"):
        return os.environ["HAND_TOOLS_BRIDGE"]
    suffix = ".exe" if os.name == "nt" else ""
    here = Path(__file__).resolve()
    for candidate in (here.parents[2] / "build/bin" / ("hand_bridge" + suffix),
                      here.parents[4] / "bin" / ("hand_bridge" + suffix)):
        if candidate.is_file():
            return str(candidate)
    return shutil.which("hand_bridge") or str(here.parents[2] / "build/bin" / ("hand_bridge" + suffix))


OPTIONS = {"sdk", "model", "side", "backend", "channel", "library", "comm", "address", "host",
           "device", "native-channel", "bitrate", "data-bitrate", "serial-baud", "parity", "slcan-protocol"}


def bridge_arguments(config):
    unknown = set(config) - OPTIONS - {"simulate"}
    if unknown:
        raise ValueError("Unknown connection options: " + ", ".join(sorted(unknown)))
    args = []
    for key, value in config.items():
        if key == "simulate":
            if not isinstance(value, bool):
                raise ValueError("simulate must be boolean")
            if value:
                args.append("--simulate")
        elif value is not None and value != "":
            if isinstance(value, (dict, list, bool)):
                raise ValueError("Connection options must be scalar")
            args.extend(("--" + key, str(value)))
    return args


class Bridge:
    def __init__(self, executable, config, timeout=15):
        self.timeout = timeout
        self.lock = threading.RLock()
        self.responses = queue.Queue(maxsize=256)
        self.logs = collections.deque(maxlen=100)
        self.sequence = 0
        self.closed = False
        self.process = subprocess.Popen([str(executable), *bridge_arguments(config)],
                                        stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace", bufsize=1)
        self.reader = threading.Thread(target=self._reader, daemon=True)
        self.reader.start()
        try:
            ready = self._next()
            if ready.get("event") != "ready":
                raise RuntimeError("Bridge did not return a ready event")
            self.meta = ready["meta"]
        except BaseException:
            self.close()
            raise

    def _reader(self):
        try:
            for line in self.process.stdout:
                if line.startswith(PREFIX):
                    try:
                        self.responses.put_nowait(json.loads(line[len(PREFIX):]))
                    except (ValueError, queue.Full):
                        self.logs.append("Invalid or overflowing bridge response")
                        break
                else:
                    self.logs.append(line.rstrip())
        finally:
            try:
                self.responses.put_nowait(None)
            except queue.Full:
                pass

    def _next(self):
        try:
            response = self.responses.get(timeout=self.timeout)
        except queue.Empty as error:
            self.close()
            raise TimeoutError("Bridge timed out and was stopped; command delivery may be uncertain. Do not retry automatically.") from error
        if response is None:
            raise RuntimeError("Bridge exited: " + " | ".join(self.logs))
        return response

    def request(self, action, channel="", values=()):
        if action not in ("meta", "read", "write", "operation"):
            raise ValueError("Unknown action")
        if channel and (not isinstance(channel, str) or not channel.replace("_", "").isalnum()):
            raise ValueError("Invalid channel")
        if action == "write":
            if not isinstance(values, (list, tuple)) or not values or len(values) > 256:
                raise ValueError("Expected a bounded numeric vector")
            if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in values):
                raise ValueError("Values must be finite numbers")
        with self.lock:
            if self.closed:
                raise RuntimeError("Bridge is closed")
            self.sequence += 1
            line = f"{self.sequence} {action} {channel}"
            if action == "write":
                line += " " + " ".join(str(value) for value in values)
            self.process.stdin.write(line + "\n")
            self.process.stdin.flush()
            response = self._next()
            if response.get("id") != self.sequence:
                self.close()
                raise RuntimeError("Bridge response mismatch; connection stopped")
            if not response.get("ok"):
                raise RuntimeError(response.get("error", "Bridge request failed"))
            return response["data"]

    def close(self):
        with self.lock:
            if self.closed:
                return
            self.closed = True
            try:
                self.process.stdin.write("0 close\n")
                self.process.stdin.flush()
            except (OSError, ValueError):
                pass
            try:
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.process.terminate()
                try:
                    self.process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait()
            for stream in (self.process.stdin, self.process.stdout):
                stream.close()
            if threading.current_thread() is not self.reader:
                self.reader.join(timeout=1)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


def catalogue(executable):
    result = subprocess.run([str(executable), "--list"], capture_output=True, text=True,
                            encoding="utf-8", timeout=10, check=True)
    return json.loads(result.stdout)
