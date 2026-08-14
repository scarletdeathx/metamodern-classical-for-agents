import json
import os
from pathlib import Path
import pty
import select
import subprocess
import time
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "mcfa"


class PersistentCliTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="mcfa-test-")
        self.environment = os.environ.copy()
        self.environment["MCFA_STATE_DIR"] = self.temporary.name

    def tearDown(self):
        self.run_cli("panic", check=False)
        self.temporary.cleanup()

    def run_cli(self, *arguments, check=True):
        return subprocess.run(
            [str(LAUNCHER), *arguments],
            cwd=ROOT,
            env=self.environment,
            text=True,
            capture_output=True,
            timeout=10,
            check=check,
        )

    def json_cli(self, *arguments):
        result = self.run_cli(*arguments)
        return json.loads(result.stdout)

    def test_daemon_survives_independent_cli_calls_and_stops_safely(self):
        started = self.json_cli(
            "start", "--backend", "null", "--sample-rate", "8000", "--block-size", "128", "--bpm", "240", "--json"
        )
        self.assertTrue(started["ok"])
        pid = started["pid"]
        self.json_cli("set", "1", "--pattern", "C2 . . C2", "--json")
        self.json_cli("set", "3", "--pattern", "F#4 . F#4 .", "--waveform", "noise", "--json")
        state = self.json_cli("status", "--json")
        self.assertTrue(state["running"])
        self.assertEqual(state["channels"][0]["loop_steps"], 4)
        self.assertEqual(state["channels"][2]["loop_steps"], 4)
        self.assertTrue(Path(self.temporary.name, "engine.pid").read_text().strip() == str(pid))
        self.run_cli("stop", "--fade", "0.05")
        saved = self.json_cli("status", "--json")
        self.assertFalse(saved["running"])
        self.assertEqual(saved["stop_reason"], "graceful-stop")

    def test_python_owned_deadline_fades_without_a_connected_client(self):
        self.json_cli(
            "start", "--backend", "null", "--sample-rate", "8000", "--block-size", "128", "--bpm", "240", "--json"
        )
        self.json_cli("set", "1", "--pattern", "C3 .", "--json")
        self.json_cli("deadline", "0.25", "--deadline-fade", "0.05", "--json")
        self.run_cli("wait", "--timeout", "3")
        saved = self.json_cli("status", "--json")
        self.assertFalse(saved["running"])
        self.assertEqual(saved["stop_reason"], "deadline")
        self.assertEqual(saved["master_volume"], 0.0)

    def test_panic_silences_and_stops_immediately(self):
        self.json_cli(
            "start", "--backend", "null", "--sample-rate", "8000", "--block-size", "128", "--bpm", "240", "--json"
        )
        self.json_cli("set", "1", "--pattern", "C3", "--json")
        panicked = self.json_cli("panic", "--json")
        self.assertTrue(panicked["panic"])
        saved = self.json_cli("status", "--json")
        self.assertFalse(saved["running"])
        self.assertEqual(saved["stop_reason"], "panic")

    def test_one_long_lived_session_controls_independent_lane_lifecycles(self):
        started = self.json_cli(
            "start", "--backend", "null", "--sample-rate", "8000", "--block-size", "256", "--bpm", "120", "--json"
        )
        process = subprocess.Popen(
            [str(LAUNCHER), "session"],
            cwd=ROOT,
            env=self.environment,
            text=True,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=1,
        )

        def exchange(message):
            process.stdin.write(json.dumps(message) + "\n")
            process.stdin.flush()
            return json.loads(process.stdout.readline())

        try:
            ready = json.loads(process.stdout.readline())
            self.assertEqual(ready["pid"], started["pid"])
            self.assertTrue(exchange({"command": "spawn", "channel": 1, "patch": {"name": "slow", "pattern": "C2 . C3", "clock": "free", "bpm": 67}})["ok"])
            self.assertTrue(exchange({"command": "spawn", "channel": 3, "patch": {"name": "fast", "pattern": "F#5 . F2 .", "clock": "free", "bpm": 173, "synth": {"waveform": "noise"}}})["ok"])
            time.sleep(0.12)
            state = exchange({"command": "status", "history": 16})["state"]
            self.assertEqual(state["schema_version"], 2)
            self.assertNotEqual(state["channels"][0]["local_beat"], state["channels"][2]["local_beat"])
            self.assertTrue(exchange({"command": "kill", "channel": 1})["ok"])
            self.assertTrue(exchange({"command": "set", "channel": 1, "patch": {"name": "replacement", "pattern": "A1 C6 .", "bpm": 91}})["ok"])
            self.assertTrue(exchange({"command": "restart", "channel": 1})["ok"])
            history = exchange({"command": "history", "limit": 40})["history"]
            self.assertTrue(any(entry["kind"] == "kill" and entry["phase"] == "applied" for entry in history))
            self.assertTrue(any(entry["kind"] == "restart" and entry["phase"] == "applied" for entry in history))
            closed = exchange({"command": "quit"})
            self.assertEqual(closed["engine"], "continues")
            process.wait(timeout=3)
            still_running = self.json_cli("status", "--compact", "--json")
            self.assertTrue(still_running["running"])
            self.assertEqual(still_running["channels"][0]["name"], "replacement")
        finally:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=3)
            process.stdin.close()
            process.stdout.close()
            process.stderr.close()

    def test_tty_session_accepts_a_multi_kilobyte_batch(self):
        """A real conductor PTY must not inherit the terminal's short line limit."""
        started = self.json_cli(
            "start", "--backend", "null", "--sample-rate", "8000", "--block-size", "256", "--bpm", "120", "--json"
        )
        master, slave = pty.openpty()
        process = subprocess.Popen(
            [str(LAUNCHER), "session"],
            cwd=ROOT,
            env=self.environment,
            stdin=slave,
            stdout=slave,
            stderr=slave,
            close_fds=True,
        )
        os.close(slave)

        def read_line(timeout=3.0):
            deadline = time.monotonic() + timeout
            data = bytearray()
            while b"\n" not in data:
                remaining = deadline - time.monotonic()
                if remaining <= 0 or not select.select([master], [], [], remaining)[0]:
                    self.fail(f"timed out reading PTY response: {bytes(data)!r}")
                data.extend(os.read(master, 65536))
            return json.loads(bytes(data).splitlines()[0])

        channels = {}
        for channel in range(1, 9):
            channels[str(channel)] = {
                "name": f"long-pty-lane-{channel}",
                "pattern": "C1 . F#6:0.42:0.31 . Eb2+A5 . G7:0.2:0.08",
                "clock": "free",
                "bpm": 47 + channel * 19,
                "step_beats": 0.11 + channel * 0.013,
                "volume": 0.04,
                "pan": -0.8 + channel * 0.18,
                "synth": {
                    "waveform": "noise" if channel % 3 == 0 else "square",
                    "attack": 0.003,
                    "decay": 0.08,
                    "sustain": 0.3,
                    "release": 0.17,
                    "detune_cents": channel * 7,
                    "filter_type": "highpass" if channel % 2 == 0 else "lowpass",
                    "cutoff_hz": 300 + channel * 700,
                    "resonance": 0.4,
                    "drive": 1.2,
                    "delay": 0.1,
                    "reverb": 0.08,
                    "modulation": {"target": "pan", "waveform": "triangle", "rate_hz": 0.3 + channel, "depth": 0.6},
                },
            }
        encoded = (json.dumps({"command": "batch", "channels": channels, "at": "now", "fade": 0.03}) + "\n").encode()
        self.assertGreater(len(encoded), 3000)

        try:
            ready = read_line()
            self.assertEqual(ready["pid"], started["pid"])
            self.assertEqual(os.write(master, encoded), len(encoded))
            accepted = read_line()
            self.assertTrue(accepted["ok"])
            self.assertEqual(accepted["scheduled"]["channels"], list(range(1, 9)))
            os.write(master, (json.dumps({"command": "status", "compact": True}) + "\n").encode())
            state = read_line()["state"]
            self.assertEqual(state["channels"][7]["name"], "long-pty-lane-8")
            os.write(master, (json.dumps({"command": "quit"}) + "\n").encode())
            self.assertEqual(read_line()["engine"], "continues")
            process.wait(timeout=3)
        finally:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=3)
            os.close(master)


if __name__ == "__main__":
    unittest.main()
