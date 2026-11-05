"""Read-only, bounded telemetry polling shared by HTTP and the full-screen UI.

Rates are requested read rates, not promises about device sampling frequency.
There is one worker and no catch-up queue; Bridge serializes reads and commands.
"""
import copy
import math
import threading
import time

DEFAULT_RATES = {
    "position": 10, "speed": 5, "configured_speed": 2, "torque": 5,
    "current": 5, "current_limit": 1, "temperature": 1, "fault": 1,
    "voltage": 1, "force": 10, "palm": 5,
    "finger_force_sum": 5, "palm_force_sum": 5,
}


class Monitor:
    def __init__(self, bridge, clock=time.monotonic):
        self.bridge = bridge
        self.clock = clock
        self.lock = threading.RLock()
        self.rates = {name: rate for name, rate in DEFAULT_RATES.items()
                      if name in bridge.meta.get("readable", [])}
        self.due = {name: 0 for name in self.rates}
        self.samples = {}
        self.sequence = 0
        self.stopped = threading.Event()
        self.worker = None

    def start(self):
        self.worker = threading.Thread(target=self._run, daemon=True, name="hand-telemetry")
        self.worker.start()

    def set_rates(self, rates):
        if not isinstance(rates, dict) or not rates:
            raise ValueError("Expected a non-empty channel/rate object")
        with self.lock:
            for name, hz in rates.items():
                if name not in self.rates:
                    raise ValueError("Unsupported monitor channel: " + str(name))
                if isinstance(hz, bool) or not isinstance(hz, (int, float)) or not math.isfinite(hz) or not 0 <= hz <= 100:
                    raise ValueError("Rate must be finite, 0 (paused) or up to 100 Hz")
            # Validate the entire update before changing any channel.
            self.rates.update(rates)
            for name in rates:
                self.due[name] = 0
            return dict(self.rates)

    def poll_once(self):
        """One fair pass; after slow reads skip missed periods instead of replaying."""
        for name in self.rates:
            if self.stopped.is_set() or self.bridge.closed or self.bridge.process.poll() is not None:
                return
            with self.lock:
                hz = self.rates[name]
                if not hz or self.clock() < self.due[name]:
                    continue
            try:
                data = self.bridge.request("read", name)
                error = None
            except (OSError, ValueError, RuntimeError) as exc:
                data, error = None, str(exc)
            with self.lock:
                self.sequence += 1
                previous = self.samples.get(name, {})
                sample = {"sequence": self.sequence, "error": error,
                          "data": previous.get("data") if error else data,
                          "received": previous.get("received") if error else self.clock()}
                self.samples[name] = sample
                # Use completion time; do not build an unbounded backlog.
                current_rate = self.rates[name]
                self.due[name] = self.clock() + (1 / current_rate if current_rate else 0)

    def snapshot(self):
        with self.lock:
            now = self.clock()
            samples = copy.deepcopy(self.samples)
            for sample in samples.values():
                received = sample.pop("received")
                sample["age_ms"] = None if received is None else max(0, (now - received) * 1000)
            return {"connected": not self.bridge.closed and self.bridge.process.poll() is None,
                    "meta": self.bridge.meta, "rates": dict(self.rates), "samples": samples}

    def _run(self):
        while not self.stopped.is_set() and not self.bridge.closed and self.bridge.process.poll() is None:
            self.poll_once()
            self.stopped.wait(0.01)

    def stop(self):
        self.stopped.set()

    def join(self):
        if self.worker and self.worker is not threading.current_thread():
            self.worker.join(timeout=self.bridge.timeout + 5)
