"""Dependency-free ANSI full-screen inspector. No SDK or protocol code lives here."""
import json
import os
import select
import shutil
import sys
import time
from contextlib import contextmanager

from .monitor import Monitor


def compact(value):
    return json.dumps(value, ensure_ascii=True, separators=(",", ":"))


def safe_text(value):
    # Device strings and errors must not be able to inject terminal control codes.
    return "".join(c if 32 <= ord(c) < 127 else "?" for c in str(value))


def sample_status(sample):
    if sample.get("error"):
        return "ERROR " + sample["error"]
    data = sample.get("data") or {}
    meta = data.get("meta", data)
    return " / ".join(str(v) for v in (
        "INVALID" if meta.get("valid") is False else "",
        "STALE" if meta.get("stale") else "",
        meta.get("origin", "unknown origin"),
        "freshness " + str(meta.get("freshness", "unknown")),
        "SDK age " + str(meta.get("age_ms", "unknown")) + " ms",
        "received " + str(round(sample["age_ms"]) if sample.get("age_ms") is not None else "?") + " ms ago",
    ) if v != "")


class Dashboard:
    views = ("Monitor", "Controls", "Tactile", "Identity")

    def __init__(self, bridge, monitor):
        self.bridge = bridge
        self.monitor = monitor
        self.view = 0
        self.offset = 0
        self.column = 0
        self.message = "Connected. No motion target, speed or torque was sent."

    def execute(self, text):
        """Only explicit write/operation commands can change hardware state."""
        parts = text.split()
        if not parts:
            return True
        command = parts[0].lower()
        try:
            if command in ("q", "quit", "exit"):
                return False
            if command == "rate" and len(parts) == 3:
                self.message = compact(self.monitor.set_rates({parts[1]: float(parts[2])}))
            elif command == "pause" and len(parts) == 1:
                self.message = compact(self.monitor.set_rates({name: 0 for name in self.monitor.rates}))
            elif command == "read" and len(parts) == 2:
                self.message = compact(self.bridge.request("read", parts[1]))
            elif command == "write" and len(parts) >= 3:
                self.message = compact(self.bridge.request("write", parts[1], [float(v) for v in parts[2:]]))
            elif command == "operation" and len(parts) == 2:
                self.message = compact(self.bridge.request("operation", parts[1]))
            else:
                self.message = "Use read CHANNEL | write CONTROL VALUES | operation NAME | rate CHANNEL HZ | pause | q"
        except (OSError, ValueError, RuntimeError) as error:
            self.message = str(error)
        return True

    def lines(self, state):
        meta = state["meta"]
        if self.view == 3:
            return json.dumps(meta, indent=2, ensure_ascii=True).splitlines()
        if self.view == 1:
            lines = ["Writes require an explicit complete raw vector. No defaults are sent.",
                     "write CONTROL v0 v1 ... | operation NAME", ""]
            for control in meta.get("controls", []):
                lines.append(control["name"] + " [" + control["unit"] + "]")
                for index, bounds in enumerate(control["ranges"]):
                    lines.append("  joint %2d: %s .. %s" % (index, bounds[0], bounds[1]))
            lines.append("Operations: " + ", ".join(meta.get("operations", [])))
            return lines
        if self.view == 2:
            lines = ["Tactile raw matrices. Units and freshness come from the SDK.", ""]
            for channel in ("force", "palm"):
                sample = state["samples"].get(channel)
                if not sample:
                    continue
                lines += [channel + ": " + sample_status(sample)]
                data = sample.get("data") or {}
                # Preserve nested legacy matrices and modern descriptor fields.
                for matrix in data.get("matrices", []):
                    raw = matrix.get("raw", [])
                    rows, cols = matrix.get("rows", 0), matrix.get("columns", 0)
                    if raw and not isinstance(raw[0], list) and rows * cols == len(raw):
                        raw = [raw[i:i + cols] for i in range(0, len(raw), cols)]
                    lines.append("  " + str(matrix.get("name", channel)))
                    lines.extend("    " + compact(row) for row in raw)
                for sensor in data.get("sensors", []):
                    lines.append("  " + str(sensor.get("name")) + " unit=" + str(sensor.get("unit")) +
                                 " available=" + str(sensor.get("available")))
                    for field in sensor.get("fields", []):
                        lines.append("    " + str(field.get("semantic")) + ": " + compact(field.get("values")))
            return lines
        lines = ["Requested read rates (Hz); 0 pauses. Slow reads skip missed periods.",
                 "  " + "  ".join(name + "=" + str(hz) for name, hz in state["rates"].items()), ""]
        vectors = {}
        for name, sample in state["samples"].items():
            raw = (sample.get("data") or {}).get("raw")
            if isinstance(raw, list) and all(not isinstance(v, (dict, list)) for v in raw):
                vectors[name] = raw
        if vectors:
            lines.append("Joint " + " ".join(name[:16].rjust(16) for name in vectors))
            for index in range(max(map(len, vectors.values()))):
                lines.append(str(index).rjust(5) + " " + " ".join(
                    str(raw[index] if index < len(raw) else "--").rjust(16) for raw in vectors.values()))
        lines += ["", "Reading health:"]
        for name, sample in state["samples"].items():
            lines.append(name + ": " + sample_status(sample))
        return lines

    def render(self, width, height, command=""):
        state = self.monitor.snapshot()
        meta = state["meta"]
        label = "SIMULATION" if meta.get("simulated") else meta.get("sdk", "")
        title = "Hand Tools | %s | %s | %s" % (meta.get("model"), label, "CONNECTED" if state["connected"] else "DISCONNECTED")
        tabs = "  ".join(("[" + view + "]") if i == self.view else view for i, view in enumerate(self.views))
        content = self.lines(state)
        page = max(1, height - 7)
        self.offset = min(max(0, self.offset), max(0, len(content) - page))
        lines = [title, tabs, "Tab: view | Arrows/PgUp/PgDn: scroll | type command + Enter | q: quit"]
        lines += [line[self.column:] for line in content[self.offset:self.offset + page]]
        lines += [""] * max(0, height - 3 - len(lines))
        # Wrap status in bounded lines so long command results remain readable.
        message = safe_text(self.message)
        lines += [message[:width], message[width:2 * width], "> " + command[-max(1, width - 3):]]
        return "\x1b[H" + "\r\n".join(safe_text(line)[:width] for line in lines[:height]) + "\x1b[J"


@contextmanager
def terminal_mode(stream=sys.stdin, output=sys.stdout):
    """Restore input mode and alternate screen on normal exit and exceptions."""
    if os.name == "nt":
        import ctypes
        kernel = ctypes.windll.kernel32
        handle = kernel.GetStdHandle(-11)
        mode = ctypes.c_ulong()
        if not kernel.GetConsoleMode(handle, ctypes.byref(mode)):
            raise OSError("Full-screen TUI requires a Windows console; use --plain")
        kernel.SetConsoleMode(handle, mode.value | 4)
        restore = lambda: kernel.SetConsoleMode(handle, mode.value)
    else:
        import termios
        import tty
        fd = stream.fileno()
        settings = termios.tcgetattr(fd)
        tty.setcbreak(fd)
        restore = lambda: termios.tcsetattr(fd, termios.TCSADRAIN, settings)
    try:
        output.write("\x1b[?1049h\x1b[?25l")
        output.flush()
        yield
    finally:
        try:
            output.write("\x1b[?25h\x1b[?1049l")
            output.flush()
        finally:
            restore()


def read_key():
    if os.name == "nt":
        import msvcrt
        if not msvcrt.kbhit():
            time.sleep(0.03)
            return ""
        key = msvcrt.getwch()
        if key in ("\x00", "\xe0"):
            return {"H": "UP", "P": "DOWN", "I": "PGUP", "Q": "PGDOWN", "K": "LEFT", "M": "RIGHT"}.get(msvcrt.getwch(), "")
        return key
    if not select.select([sys.stdin], [], [], 0.05)[0]:
        return ""
    key = os.read(sys.stdin.fileno(), 1).decode("ascii", errors="ignore")
    if key == "\x1b":
        sequence = ""
        while select.select([sys.stdin], [], [], 0.01)[0] and len(sequence) < 8:
            sequence += os.read(sys.stdin.fileno(), 1).decode("ascii", errors="ignore")
        return {"[A": "UP", "[B": "DOWN", "[5~": "PGUP", "[6~": "PGDOWN", "[D": "LEFT", "[C": "RIGHT"}.get(sequence, "ESC")
    return key or "EOF"


def run(bridge):
    monitor = Monitor(bridge)
    dashboard = Dashboard(bridge, monitor)
    text = ""
    monitor.start()
    try:
        with terminal_mode():
            while True:
                width, height = shutil.get_terminal_size((100, 30))
                sys.stdout.write(dashboard.render(max(20, width), max(8, height), text))
                sys.stdout.flush()
                key = read_key()
                if key in ("\x03", "EOF") or key == "q" and not text:
                    break
                if key == "\t":
                    dashboard.view = (dashboard.view + 1) % len(dashboard.views)
                    dashboard.offset = 0
                    dashboard.column = 0
                elif key in ("LEFT", "RIGHT"):
                    dashboard.column = max(0, dashboard.column + (16 if key == "RIGHT" else -16))
                elif key in ("UP", "DOWN", "PGUP", "PGDOWN"):
                    dashboard.offset += {"UP": -1, "DOWN": 1, "PGUP": -10, "PGDOWN": 10}[key]
                elif key in ("\r", "\n"):
                    if not dashboard.execute(text):
                        break
                    text = ""
                elif key == "ESC":
                    text = ""
                elif key in ("\x7f", "\b"):
                    text = text[:-1]
                elif len(key) == 1 and 32 <= ord(key) < 127 and len(text) < 4096:
                    text += key
    except KeyboardInterrupt:
        pass
    finally:
        monitor.stop()
        # Stop outstanding SDK reads before waiting for the telemetry worker.
        bridge.close()
        monitor.join()
