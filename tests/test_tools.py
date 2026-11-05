"""Offline process, terminal and HTTP contract tests. No physical SDK is opened."""
import argparse
import hashlib
import http.client
import json
import os
import select
import time
from pathlib import Path
import subprocess
import sys
import threading
import unittest

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / "python"))
from hand_tools.client import Bridge, catalogue
from hand_tools.server import create_server

parser = argparse.ArgumentParser()
parser.add_argument("--bridge", required=True)
options, remaining = parser.parse_known_args()
executable = str(Path(options.bridge).resolve())
sys.argv = [sys.argv[0], *remaining]


class ProcessTests(unittest.TestCase):
    def test_catalogue_has_full_baseline(self):
        models = {p["model"]: p["preferred_sdk"] for p in catalogue(executable)["models"]}
        self.assertEqual(set(models), {"L6", "O6", "L7", "L20_LITE", "L20", "L20_10", "L21", "L25", "O20", "L30", "O30"})
        self.assertEqual(models["O30"], "modern")
        self.assertEqual(models["O20"], "legacy")

    def test_all_models_have_explicit_offline_connection(self):
        for model in catalogue(executable)["models"]:
            with self.subTest(model=model), Bridge(executable, {"model": model["model"], "simulate": True}) as hand:
                self.assertTrue(hand.meta["simulated"])
                self.assertEqual(hand.meta["sdk"], "simulation")
                self.assertEqual(hand.request("read", "force")["origin"], "simulation")

    def test_aliases(self):
        for alias, canonical in (("G20", "L20_10"), ("L20_11", "L20_10"), ("L10", "L20_LITE")):
            with self.subTest(alias=alias), Bridge(executable, {"model": alias, "simulate": True}) as hand:
                self.assertEqual(hand.meta["model"], canonical)

    def test_vector_validation_and_readback(self):
        with Bridge(executable, {"model": "L7", "simulate": True}) as hand:
            hand.request("write", "position", [20] * 7)
            self.assertEqual(hand.request("read", "position")["raw"], [20] * 7)
            for values in ([0] * 6, [300] * 7):
                with self.assertRaises(RuntimeError):
                    hand.request("write", "position", values)
            for values in ([float("nan")] * 7, [True] * 7):
                with self.assertRaises(ValueError):
                    hand.request("write", "position", values)
            self.assertEqual(hand.request("read", "position")["raw"], [20] * 7)
            with self.assertRaises(RuntimeError):
                hand.request("operation", "enable")

    def test_invalid_profiles_fail_without_fallback(self):
        for args in (("--model", "missing"), ("--model", "L7", "--sdk", "modern"),
                     ("--model", "O6", "--comm", "modbus"), ("--side", "missing")):
            simulator = str(Path(executable).with_name("hand_simulator" + Path(executable).suffix))
            result = subprocess.run([simulator, "--simulate", *args], capture_output=True, text=True, timeout=10)
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn('"event":"ready"', result.stdout)

    def test_close_prevents_further_commands(self):
        hand = Bridge(executable, {"simulate": True})
        hand.close()
        hand.close()
        self.assertIsNotNone(hand.process.poll())
        with self.assertRaises(RuntimeError):
            hand.request("read", "position")

    def test_terminal_uses_shared_backend(self):
        result = subprocess.run([sys.executable, str(root / "hand-tools.py"), "tui", "--simulate", "--bridge", executable],
                                input="read force\nquit\n", capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('"simulation"', result.stdout)

    @unittest.skipIf(os.name == "nt", "POSIX PTY integration")
    def test_fullscreen_l30_o30_without_hardware(self):
        import pty
        for model in ("L30", "O30"):
            master, slave = pty.openpty()
            import fcntl
            import struct
            import termios
            fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 40, 120, 0, 0))
            environment = dict(os.environ, COLUMNS="120", LINES="40")
            child = subprocess.Popen([sys.executable, str(root / "hand-tools.py"), "tui", "--simulate",
                                      "--model", model, "--bridge", executable],
                                     stdin=slave, stdout=slave, stderr=slave, close_fds=True, env=environment)
            output = b""
            try:
                deadline = time.monotonic() + 10
                while b"No motion target" not in output and time.monotonic() < deadline:
                    if select.select([master], [], [], .1)[0]:
                        output += os.read(master, 65536)
                self.assertIn(model.encode(), output)
                self.assertIn(b"SIMULATION", output)
                self.assertIn(b"No motion target", output)
                os.write(master, b"q")
                deadline = time.monotonic() + 5
                # Drain concurrently: a full PTY output queue can block screen restore.
                while time.monotonic() < deadline:
                    if select.select([master], [], [], .1)[0]:
                        try:
                            output += os.read(master, 65536)
                        except OSError:
                            break
                    if child.poll() is not None and b"\x1b[?1049l" in output:
                        break
                child.wait(timeout=1)
                self.assertEqual(child.returncode, 0)
                self.assertIn(b"\x1b[?1049h", output)
                self.assertIn(b"\x1b[?1049l", output)
            finally:
                if child.poll() is None:
                    child.kill()
                    child.wait()
                os.close(master)
                os.close(slave)

    def test_historical_sources_are_intact(self):
        history = root / "historical/v2.2.1"
        manifest = json.loads((history / "manifest.json").read_text())
        for record in manifest["files"]:
            with self.subTest(file=record["path"]):
                self.assertEqual(hashlib.sha256((history / record["path"]).read_bytes()).hexdigest(), record["sha256"])
        for required in ("examples/hand_tui.cpp", "examples/test_o30_canfd_0.cpp", "examples/test_l30_canfd_socket_0.cpp", "webui/run.py", "webui/static/app.js"):
            self.assertTrue((history / required).is_file())


class HttpTests(unittest.TestCase):
    def setUp(self):
        self.server = create_server(executable, port=0)
        self.worker = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.worker.start()

    def tearDown(self):
        self.server.manager.close()
        self.server.shutdown()
        self.server.server_close()
        self.worker.join(timeout=2)

    def request(self, path, payload=None, origin=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=10)
        headers = {"Content-Type": "application/json"}
        if origin:
            headers["Origin"] = origin
        connection.request("GET" if payload is None else "POST", path,
                           body=None if payload is None else json.dumps(payload), headers=headers)
        response = connection.getresponse()
        body = response.read()
        status = response.status
        connection.close()
        return status, body

    def test_browser_connection_and_tactile_read(self):
        status, body = self.request("/")
        self.assertEqual(status, 200)
        self.assertIn(b"LinkerBot Hand Tools", body)
        status, body = self.request("/api/connect", {"model": "O30", "simulate": True})
        self.assertEqual(status, 200)
        self.assertTrue(json.loads(body)["data"]["simulated"])
        status, body = self.request("/api/request", {"action": "read", "channel": "force"})
        self.assertEqual(status, 200)
        self.assertEqual(len(json.loads(body)["data"]["matrices"][0]["raw"]), 2)
        self.assertEqual(self.request("/api/connect", {"simulate": True})[0], 400)
        self.assertEqual(self.request("/api/disconnect", {})[0], 200)
        self.assertEqual(self.request("/api/request", {"action": "read", "channel": "position"})[0], 400)

    def test_simultaneous_monitor_rates_and_read_only_connection(self):
        for model, count in (("L30", 17), ("O30", 20)):
            self.assertEqual(self.request("/api/connect", {"model": model, "simulate": True})[0], 200)
            deadline = time.monotonic() + 5
            state = {}
            while time.monotonic() < deadline:
                state = json.loads(self.request("/api/state")[1])
                if {"position", "temperature", "fault", "force", "palm"} <= set(state["samples"]):
                    break
                time.sleep(.02)
            self.assertTrue(state["connected"])
            self.assertEqual(state["samples"]["position"]["data"]["raw"], [0] * count)
            self.assertIn("matrices", state["samples"]["force"]["data"])
            self.assertIn("matrices", state["samples"]["palm"]["data"])
            rates = {name: 0 for name in state["rates"]}
            self.assertEqual(self.request("/api/rates", rates)[0], 200)
            self.assertEqual(self.request("/api/rates", {"force": 30})[0], 200)
            for bad in ({"force": -1}, {"force": 101}, {"force": True}, {"missing": 2}, {"force": "10"}):
                self.assertEqual(self.request("/api/rates", bad)[0], 400)
            self.assertEqual(self.request("/api/rates", {"force": 1}, origin="http://other.example")[0], 403)
            self.assertEqual(json.loads(self.request("/api/request", {"action":"read", "channel":"position"})[1])["data"]["raw"], [0] * count)
            self.assertEqual(self.request("/api/disconnect", {})[0], 200)
            self.assertFalse(json.loads(self.request("/api/state")[1])["connected"])

    def test_dead_bridge_can_reconnect_and_state_does_not_claim_connected(self):
        self.assertEqual(self.request("/api/connect", {"model": "O30", "simulate": True})[0], 200)
        connection_id = json.loads(self.request("/api/state")[1])["connection_id"]
        self.server.manager.bridge.close()
        self.assertFalse(json.loads(self.request("/api/state")[1])["connected"])
        self.assertIsNone(json.loads(self.request("/api/meta")[1]))
        self.assertEqual(self.request("/api/connect", {"model": "L30", "simulate": True})[0], 200)
        state = json.loads(self.request("/api/state")[1])
        self.assertEqual(state["meta"]["model"], "L30")
        self.assertGreater(state["connection_id"], connection_id)

    def test_reject_cross_origin_and_unknown_connection_fields(self):
        self.assertEqual(self.request("/api/connect", {"simulate": True}, origin="http://other.example")[0], 403)
        self.assertEqual(self.request("/api/connect", {"simulate": True, "bridge": "arbitrary-program"})[0], 400)
        self.assertIsNone(self.server.manager.bridge)
        self.assertEqual(self.request("/../LICENSE")[0], 404)


if __name__ == "__main__":
    unittest.main(verbosity=2)
