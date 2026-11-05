"""Read-only scheduling, failure semantics and full-screen contracts."""
import copy
import io
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'python'))
from hand_tools.monitor import Monitor
from hand_tools.tui import Dashboard, terminal_mode


class Process:
    def poll(self):
        return None


class FakeBridge:
    timeout = 0.1
    closed = False
    process = Process()

    def __init__(self, model='O30', size=20):
        self.meta = {'model': model, 'sdk': 'modern', 'simulated': False,
                     'readable': ['position', 'speed', 'force', 'palm', 'temperature', 'fault'],
                     'controls': [{'name': 'position', 'unit': 'raw count', 'ranges': [[-100, 200]] * size}],
                     'operations': ['enable', 'disable']}
        self.calls = []
        self.error = None

    def request(self, action, channel='', values=()):
        self.calls.append((action, channel, values))
        if self.error:
            raise self.error
        return {'raw': list(range(len(self.meta['controls'][0]['ranges']))),
                'meta': {'origin': 'device_measured', 'valid': True, 'stale': False}}


class MonitorTests(unittest.TestCase):
    def setUp(self):
        self.now = 100
        self.bridge = FakeBridge()
        self.monitor = Monitor(self.bridge, lambda: self.now)

    def test_connect_poll_rates_and_render_never_write(self):
        for model, count in [('L30', 17), ('O30', 20)]:
            bridge = FakeBridge(model, count)
            monitor = Monitor(bridge)
            monitor.poll_once()
            dashboard = Dashboard(bridge, monitor)
            for view in range(4):
                dashboard.view = view
                text = dashboard.render(200, 60)
                self.assertIn(model, text)
                if view == 1:
                    self.assertIn('joint %2d' % (count - 1), text)
            dashboard.execute('rate force 30')
            dashboard.execute('pause')
            self.assertTrue(all(call[0] == 'read' for call in bridge.calls))

    def test_independent_rates_pause_and_no_catchup(self):
        self.monitor.set_rates({name: 0 for name in self.monitor.rates})
        self.monitor.set_rates({'position': 10, 'force': 1})
        self.monitor.poll_once()
        self.assertEqual([c[1] for c in self.bridge.calls], ['position', 'force'])
        self.now += .11
        self.monitor.poll_once()
        self.assertEqual([c[1] for c in self.bridge.calls], ['position', 'force', 'position'])
        self.now += 100
        self.bridge.calls.clear()
        self.monitor.poll_once()
        self.assertEqual(len(self.bridge.calls), 2)
        self.monitor.set_rates({'force': 0, 'position': 0})
        self.now += 100
        self.monitor.poll_once()
        self.assertEqual(len(self.bridge.calls), 2)

    def test_rate_validation_is_atomic(self):
        original = self.monitor.snapshot()['rates']
        for rates in ({'position': 20, 'missing': 1}, {'force': True}, {'force': float('nan')},
                      {'force': -1}, {'force': 101}, [], {}, {'operation': 1}):
            with self.assertRaises(ValueError):
                self.monitor.set_rates(rates)
            self.assertEqual(self.monitor.snapshot()['rates'], original)

    def test_error_retains_original_data_and_receipt_age(self):
        self.monitor.poll_once()
        self.now += 2
        self.bridge.error = RuntimeError('disconnected')
        self.monitor.poll_once()
        state = self.monitor.snapshot()
        self.assertEqual(state['samples']['position']['age_ms'], 2000)
        self.assertEqual(state['samples']['position']['error'], 'disconnected')
        self.assertTrue(state['samples']['position']['data']['meta']['valid'])
        # Snapshot must not let clients mutate stored SDK metadata.
        state['samples']['position']['data']['meta']['valid'] = False
        self.assertTrue(self.monitor.snapshot()['samples']['position']['data']['meta']['valid'])
        self.bridge.closed = True
        self.assertFalse(self.monitor.snapshot()['connected'])
        size = len(self.bridge.calls)
        self.monitor.poll_once()
        self.assertEqual(len(self.bridge.calls), size)

    def test_slow_read_uses_completion_time(self):
        self.monitor.set_rates({name: 0 for name in self.monitor.rates})
        self.monitor.set_rates({'position': 10})
        def slow(*_):
            self.now += 5
            return {'raw': [1]}
        self.bridge.request = slow
        self.monitor.poll_once()
        self.assertAlmostEqual(self.monitor.due['position'], 105.1)
        self.assertEqual(self.monitor.snapshot()['samples']['position']['age_ms'], 0)

    def test_tui_requires_explicit_action_and_surfaces_command_stage(self):
        dashboard = Dashboard(self.bridge, self.monitor)
        self.assertEqual(self.bridge.calls, [])
        dashboard.execute('write position ' + ' '.join(['10'] * 20))
        self.assertEqual(self.bridge.calls[-1], ('write', 'position', [10.0] * 20))
        dashboard.execute('operation enable')
        self.assertEqual(self.bridge.calls[-1][:2], ('operation', 'enable'))
        self.bridge.error = RuntimeError('out of range')
        dashboard.execute('write position 999')
        self.assertIn('out of range', dashboard.message)
        self.assertFalse(dashboard.execute('quit'))

    def test_tui_sanitizes_device_escape_codes_and_tiny_layout(self):
        dashboard = Dashboard(self.bridge, self.monitor)
        dashboard.message = '\x1b[2Jbad\nline'
        text = dashboard.render(20, 8)
        self.assertNotIn('\x1b[2J', text)
        self.assertLessEqual(len(text.split('\r\n')), 8)

    @unittest.skipIf(sys.platform == 'win32', 'POSIX terminal restoration')
    def test_terminal_restored_even_on_exception(self):
        import pty
        import os
        import termios
        master, slave = pty.openpty()
        try:
            stream = os.fdopen(os.dup(slave))
            original = termios.tcgetattr(slave)
            output = io.StringIO()
            with self.assertRaises(RuntimeError):
                with terminal_mode(stream, output):
                    raise RuntimeError('render failed')
            restored = termios.tcgetattr(slave)
            # macOS PTYs can add EXTPROC when tcsetattr restores canonical mode.
            # Compare all other bits, including ECHO/ICANON/ISIG and all control chars.
            if sys.platform == 'darwin':
                restored[3] &= ~0x20000000
                original[3] &= ~0x20000000
            self.assertEqual(restored, original)
            self.assertIn('\x1b[?1049l', output.getvalue())
            self.assertIn('\x1b[?25h', output.getvalue())
            stream.close()
        finally:
            os.close(master)
            os.close(slave)


if __name__ == '__main__':
    unittest.main()
