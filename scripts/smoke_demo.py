#!/usr/bin/env python3
"""End-to-end smoke test for MCFA's independent noise-lane conductor."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time


ROOT = Path(__file__).resolve().parents[1]
MCFA = ROOT / "mcfa"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend", choices=("null", "sounddevice"), default="null")
    parser.add_argument("--state-dir", type=Path)
    parser.add_argument("--duration", type=float, default=2.0, help="Python-owned performance seconds")
    parser.add_argument("--keep-state", action="store_true")
    args = parser.parse_args()
    temporary = None
    if args.state_dir is None:
        if args.keep_state:
            state_dir = Path(tempfile.mkdtemp(prefix="mcfa-noise-smoke-"))
        else:
            temporary = tempfile.TemporaryDirectory(prefix="mcfa-noise-smoke-")
            state_dir = Path(temporary.name)
    else:
        state_dir = args.state_dir.expanduser().resolve()
    environment = os.environ.copy()
    environment["MCFA_STATE_DIR"] = str(state_dir)

    def run(*arguments: str, parse_json: bool = False):
        result = subprocess.run(
            [str(MCFA), *arguments],
            cwd=ROOT,
            env=environment,
            text=True,
            capture_output=True,
            timeout=max(15.0, args.duration + 5.0),
        )
        if result.returncode:
            raise RuntimeError(f"{' '.join(arguments)} failed:\n{result.stderr}\n{result.stdout}")
        return json.loads(result.stdout) if parse_json else result.stdout.strip()

    session = None
    try:
        print(f"[1/7] Starting one supervised {args.backend} mixer")
        started = run(
            "start", "--backend", args.backend, "--bpm", "127", "--master-volume", "0.48", "--json",
            parse_json=True,
        )
        engine_pid = started["pid"]
        session = subprocess.Popen(
            [str(MCFA), "session"],
            cwd=ROOT,
            env=environment,
            text=True,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=1,
        )
        ready = json.loads(session.stdout.readline())
        assert ready["pid"] == engine_pid

        def exchange(message: dict):
            session.stdin.write(json.dumps(message) + "\n")
            session.stdin.flush()
            response = json.loads(session.stdout.readline())
            if not response.get("ok"):
                raise RuntimeError(f"session rejected {message}: {response}")
            return response

        print("[2/7] Spawning lanes 1 and 3 on unrelated free clocks")
        exchange(
            {"command": "spawn", "channel": 1, "patch": {"name": "slow fracture", "pattern": "C1 . C6 . F#2", "clock": "free", "bpm": 61, "step_beats": 0.31, "volume": 0.18, "synth": {"waveform": "square", "modulation": {"target": "cutoff", "rate_hz": 0.37, "depth": 0.8}}}}
        )
        exchange(
            {"command": "spawn", "channel": 3, "patch": {"name": "fast grit", "pattern": "F#5 . C2 F6 . A1", "clock": "free", "bpm": 193, "step_beats": 0.17, "volume": 0.12, "pan": 0.6, "synth": {"waveform": "noise", "modulation": {"target": "pan", "rate_hz": 6.1, "depth": 0.7}}}}
        )
        time.sleep(0.2)
        first = exchange({"command": "status", "history": 12})["state"]
        assert first["channels"][0]["local_beat"] != first["channels"][2]["local_beat"]

        print("[3/7] Expanding through the same session to all ten sound machines")
        lanes = {
            "1": {"name": "slow fracture", "pattern": "C1 . C6 . F#2", "clock": "free", "bpm": 61, "step_beats": 0.31, "volume": 0.15, "synth": {"waveform": "square"}},
            "2": {"name": "sub swarm", "pattern": "C1 C2 . Eb1 . G1", "clock": "free", "bpm": 83, "step_beats": 0.41, "volume": 0.13, "pan": -0.5, "synth": {"waveform": "saw", "modulation": {"target": "amplitude", "rate_hz": 0.7, "depth": 0.75}}},
            "3": {"name": "fast grit", "pattern": "F#5 . C2 F6 . A1", "clock": "free", "bpm": 193, "step_beats": 0.17, "volume": 0.1, "pan": 0.6, "synth": {"waveform": "noise"}},
            "4": {"name": "crooked knocks", "pattern": "D2 . . D5 . Bb1 .", "clock": "free", "bpm": 109, "step_beats": 0.23, "volume": 0.12, "pan": -0.2, "synth": {"waveform": "sine"}},
            "5": {"name": "cluster fog", "pattern": "C3+C#3+F#3:0.4:2 . . G2+Ab2+D3:0.35:2 .", "clock": "free", "bpm": 47, "step_beats": 0.8, "volume": 0.09, "pan": 0.2, "synth": {"waveform": "saw", "effects": {"reverb_mix": 0.35}}},
            "6": {"name": "needle", "pattern": ". C7 . F#6 G6 .", "clock": "free", "bpm": 251, "step_beats": 0.13, "volume": 0.055, "pan": 0.8, "synth": {"waveform": "triangle", "modulation": {"target": "pan", "rate_hz": 11, "depth": 0.9}}},
            "7": {"name": "rust pulse", "pattern": "A2 . C3 . Eb2 . F#4", "clock": "free", "bpm": 137, "step_beats": 0.29, "volume": 0.08, "pan": -0.75, "synth": {"waveform": "square", "effects": {"drive": 0.5}}},
            "8": {"name": "radio dust", "pattern": "C5 F#1 . C6 . D2", "clock": "free", "bpm": 157, "step_beats": 0.19, "volume": 0.07, "synth": {"waveform": "noise", "modulation": {"target": "amplitude", "rate_hz": 13, "depth": 0.95}}},
            "9": {"name": "long metal", "pattern": "C2+F#2+B2:0.3:3 . . .", "clock": "free", "bpm": 37, "step_beats": 1.1, "volume": 0.07, "pan": 0.45, "synth": {"waveform": "triangle", "effects": {"delay_mix": 0.3, "delay_feedback": 0.6}}},
            "10": {"name": "optional grid", "pattern": "C4 . F5 .", "clock": "sync", "step_beats": 0.25, "volume": 0.05, "pan": -0.1, "synth": {"waveform": "sine"}},
        }
        exchange({"command": "batch", "channels": lanes, "at": "now", "fade": 0.05})
        time.sleep(0.25)
        all_ten = exchange({"command": "status", "history": 20})["state"]
        assert sum(channel["active"] and channel["loop_steps"] > 0 for channel in all_ten["channels"]) == 10
        assert len({round(channel["local_beat"], 2) for channel in all_ten["channels"][:9]}) >= 5

        print("[4/7] Killing, rewriting, and reviving lanes without touching their neighbors")
        exchange({"command": "kill", "channel": 3})
        exchange({"command": "set", "channel": 3, "patch": {"name": "reborn splinters", "pattern": "C7 C1 . Eb6 F#2 . A6", "bpm": 211, "step_beats": 0.11, "synth": {"waveform": "saw", "modulation": {"target": "cutoff", "rate_hz": 17, "depth": 1}}}})
        exchange({"command": "restart", "channel": 3, "fade": 0.08})
        exchange({"command": "mute", "channel": 5, "fade": 0.05})
        exchange({"command": "set", "channel": 5, "patch": {"pattern": "C2+C#4+G6 . F1+B3 .", "bpm": 53}})
        exchange({"command": "unmute", "channel": 5, "at": "next-step", "fade": 0.08})
        exchange({"command": "set", "channel": 10, "patch": {"pan": 0.7}, "at": "next-beat", "fade": 0.1})

        print("[5/7] Starting the Python deadline while the conductor remains connected")
        exchange({"command": "deadline", "seconds": args.duration, "deadline_fade": min(0.4, args.duration / 3)})
        midpoint = time.monotonic() + args.duration * 0.45
        while time.monotonic() < midpoint:
            time.sleep(0.03)
        exchange({"command": "kill", "channel": 7})
        exchange({"command": "spawn", "channel": 7, "patch": {"name": "last scrape", "pattern": "C1 C7 F#1 F#7", "clock": "free", "bpm": 227, "step_beats": 0.09, "volume": 0.06, "synth": {"waveform": "noise"}}})
        during = exchange({"command": "status", "history": 64})["state"]
        assert during["deadline"]["active"] and during["running"]

        print("[6/7] Verifying the event history before the owned fade")
        history = exchange({"command": "history", "limit": 128})["history"]
        applied_kinds = [entry["kind"] for entry in history if entry["phase"] == "applied"]
        assert "kill" in applied_kinds and "restart" in applied_kinds and "batch" in applied_kinds
        assert any(entry["decision"].get("name") == "reborn splinters" for entry in history)

        print("[7/7] Waiting for deadline fade and safe mixer stop")
        run("wait", "--timeout", str(args.duration + 5))
        final = run("status", "--compact", "--history", "128", "--json", parse_json=True)
        assert not final["running"] and final["stop_reason"] == "deadline"
        assert final["master_volume"] == 0.0
        # One isolated scheduling miss during the intentionally huge ten-lane
        # spawn burst is tolerated; sustained misses (like the previous 44) fail.
        assert final["health"]["underruns"] <= 1
        assert any(entry["kind"] == "deadline-complete" for entry in final["history"])
        print(
            f"PASS: PID {engine_pid}, one persistent conductor, 10 independent lanes, "
            f"kill/rewrite/restart, sync+free changes, history, {final['health']['underruns']} underruns, safe deadline"
        )
        print(f"Saved final state: {state_dir / 'state.json'}")
        return 0
    except Exception:
        try:
            run("panic")
        except Exception:
            pass
        raise
    finally:
        if session is not None:
            if session.poll() is None:
                session.terminate()
                try:
                    session.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    session.kill()
            for stream in (session.stdin, session.stdout, session.stderr):
                if stream is not None:
                    stream.close()
        if temporary is not None and not args.keep_state:
            temporary.cleanup()


if __name__ == "__main__":
    raise SystemExit(main())
