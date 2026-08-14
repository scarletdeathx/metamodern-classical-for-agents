"""Command-line client for the persistent MCFA engine."""

from __future__ import annotations

import argparse
import copy
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from typing import Any

from .daemon import PID_NAME, SOCKET_NAME, STATE_NAME
from .model import (
    CLOCK_MODES,
    FILTER_TYPES,
    MAX_CHANNELS,
    MODULATION_TARGETS,
    MODULATION_WAVEFORMS,
    WAVEFORMS,
    ValidationError,
    parse_pattern,
    pattern_from_json,
    validate_channel_id,
)


def default_state_dir() -> Path:
    override = os.environ.get("MCFA_STATE_DIR")
    if override:
        return Path(override).expanduser()
    return Path.home() / "Library" / "Application Support" / "Metamodern Classical for Agents"


class EngineConnection:
    """A reusable newline-delimited JSON connection to one running engine."""

    def __init__(self, state_dir: Path, timeout: float | None = 3.0) -> None:
        self.client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.client.settimeout(timeout)
        self.client.connect(str(state_dir / SOCKET_NAME))
        self.reader = self.client.makefile("rb")

    def request(self, message: dict[str, Any]) -> dict[str, Any]:
        self.client.sendall(json.dumps(message, separators=(",", ":")).encode() + b"\n")
        raw = self.reader.readline(4_194_305)
        if not raw:
            raise RuntimeError("engine closed the connection without a response")
        if len(raw) > 4_194_304:
            raise RuntimeError("engine response exceeds 4 MiB")
        response = json.loads(raw)
        if not response.get("ok"):
            raise ValidationError(response.get("error", "engine rejected the command"))
        return response

    def close(self) -> None:
        try:
            self.reader.close()
        finally:
            self.client.close()

    def __enter__(self) -> "EngineConnection":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()


def request(state_dir: Path, message: dict[str, Any], timeout: float = 3.0) -> dict[str, Any]:
    with EngineConnection(state_dir, timeout=timeout) as connection:
        return connection.request(message)


def ping(state_dir: Path, timeout: float = 0.25) -> dict[str, Any] | None:
    try:
        return request(state_dir, {"command": "ping"}, timeout=timeout)
    except (OSError, RuntimeError, ValueError):
        return None


def command_start(args: argparse.Namespace) -> int:
    state_dir = args.state_dir.expanduser().resolve()
    state_dir.mkdir(parents=True, exist_ok=True)
    current = ping(state_dir)
    if current and current.get("running"):
        raise ValidationError(f"MCFA is already running as PID {current['pid']}")

    socket_path = state_dir / SOCKET_NAME
    pid_path = state_dir / PID_NAME
    if pid_path.exists():
        try:
            old_pid = int(pid_path.read_text(encoding="ascii").strip())
            os.kill(old_pid, 0)
        except (ValueError, OSError):
            pid_path.unlink(missing_ok=True)
            socket_path.unlink(missing_ok=True)
        else:
            raise RuntimeError(
                f"PID {old_pid} is alive but its MCFA socket is unavailable; "
                f"inspect {state_dir / 'engine.log'} before removing stale runtime files"
            )
    else:
        socket_path.unlink(missing_ok=True)

    if not 0.0 <= args.master_volume <= 1.0:
        raise ValidationError("master volume must be between 0 and 1")
    if args.duration is not None and args.duration <= 0:
        raise ValidationError("duration must be greater than zero")
    if args.duration is not None and not 0 <= args.deadline_fade <= args.duration:
        raise ValidationError("deadline fade must be between zero and duration")

    module_root = Path(__file__).resolve().parents[1]
    environment = os.environ.copy()
    old_pythonpath = environment.get("PYTHONPATH")
    environment["PYTHONPATH"] = str(module_root) + (os.pathsep + old_pythonpath if old_pythonpath else "")
    child_args = [
        sys.executable,
        "-m",
        "mcfa.daemon",
        "--state-dir",
        str(state_dir),
        "--backend",
        args.backend,
        "--bpm",
        str(args.bpm),
        "--sample-rate",
        str(args.sample_rate),
        "--block-size",
        str(args.block_size),
        "--master-volume",
        str(args.master_volume),
        "--deadline-fade",
        str(args.deadline_fade),
    ]
    if args.duration is not None:
        child_args.extend(("--duration", str(args.duration)))
    if args.device is not None:
        child_args.extend(("--device", str(args.device)))
    log_path = state_dir / "engine.log"
    log = log_path.open("a", encoding="utf-8")
    log.write(f"\n--- MCFA start {time.strftime('%Y-%m-%d %H:%M:%S')} ---\n")
    log.flush()
    process = subprocess.Popen(
        child_args,
        stdin=subprocess.DEVNULL,
        stdout=log,
        stderr=log,
        env=environment,
        start_new_session=True,
        close_fds=True,
    )
    log.close()
    deadline = time.monotonic() + args.startup_timeout
    response = None
    while time.monotonic() < deadline:
        if process.poll() is not None:
            break
        response = ping(state_dir)
        if response and response.get("running"):
            break
        time.sleep(0.05)
    if not response or not response.get("running"):
        tail = _tail(log_path, 30)
        detail = f"\n{tail}" if tail else ""
        raise RuntimeError(f"MCFA failed to start; see {log_path}{detail}")
    result = {
        "ok": True,
        "pid": response["pid"],
        "backend": args.backend,
        "bpm": args.bpm,
        "state_dir": str(state_dir),
        "duration": args.duration,
    }
    _print_result(args, result, f"MCFA started (PID {response['pid']}, {args.backend}, {args.bpm:g} BPM)")
    return 0


def command_status(args: argparse.Namespace) -> int:
    state_dir = args.state_dir.expanduser().resolve()
    live = True
    try:
        message: dict[str, Any] = {"command": "status"}
        if args.compact:
            message.update({"compact": True, "history": args.history})
        state = request(state_dir, message)["state"]
    except (OSError, RuntimeError):
        state_path = state_dir / STATE_NAME
        if not state_path.exists():
            raise RuntimeError("MCFA is not running and no saved state exists; run 'mcfa start'")
        state = json.loads(state_path.read_text(encoding="utf-8"))
        state["running"] = False
        if args.compact:
            state = _compact_saved_state(state, args.history)
        live = False
    if args.channel is not None:
        channel = state["channels"][args.channel - 1]
        if args.json:
            print(json.dumps(channel, indent=2, sort_keys=True))
        else:
            _print_channel_detail(channel, live)
    elif args.json:
        print(json.dumps(state, indent=2, sort_keys=True))
    elif args.compact:
        _print_compact_status(state, live)
    else:
        _print_status_table(state, live)
    return 0


def _compact_saved_state(state: dict[str, Any], history_limit: int) -> dict[str, Any]:
    channels = []
    for channel in state.get("channels", []):
        runtime = channel.get("runtime", {})
        synth = channel.get("synth", {})
        channels.append(
            {
                "id": channel["id"],
                "name": channel.get("name", ""),
                "active": channel.get("active", True),
                "muted": channel.get("muted", False),
                "clock": channel.get("clock", "sync"),
                "bpm": channel.get("bpm", state.get("bpm", 120)),
                "step_beats": channel.get("step_beats", 0.25),
                "random_seed": channel.get("random_seed"),
                "loop_steps": channel.get("loop_steps", len(channel.get("pattern", []))),
                "loop_seconds": channel.get("loop_seconds", 0.0),
                "waveform": synth.get("waveform", "sine"),
                "volume": channel.get("volume", 0.0),
                "pan": channel.get("pan", 0.0),
                "modulation": synth.get("modulation", {}).get("target", "off"),
                "voices": runtime.get("active_voices", 0),
                "local_beat": runtime.get("local_beat", state.get("transport", {}).get("beat", 0.0)),
                "level": runtime.get("level", {"peak": 0.0, "rms": 0.0}),
            }
        )
    compact = {
        key: copy.deepcopy(state.get(key))
        for key in ("schema_version", "entropy_stamp", "running", "backend", "sample_rate", "bpm", "master_volume", "transport", "deadline", "scheduled", "health", "stop_reason")
    }
    compact["channels"] = channels
    limit = max(0, int(history_limit))
    compact["history"] = copy.deepcopy(state.get("history", [])[-limit:]) if limit else []
    return compact


def _session_pattern(value: Any) -> Any:
    if isinstance(value, str):
        return [step.public() for step in parse_pattern(value)]
    return value


def _normalize_session_request(raw: dict[str, Any]) -> dict[str, Any]:
    """Translate compact conductor messages into the engine protocol."""
    if not isinstance(raw, dict):
        raise ValidationError("session input must be a JSON object")
    command = str(raw.get("command", ""))
    if not command:
        raise ValidationError("session input requires command")
    message: dict[str, Any] = {"command": command}
    for key in ("at", "fade"):
        if key in raw:
            message[key] = raw[key]

    if "payload" in raw:
        payload = copy.deepcopy(raw["payload"])
        if command in {"set", "batch"}:
            if command == "set" and isinstance(payload.get("patch"), dict) and "pattern" in payload["patch"]:
                payload["patch"]["pattern"] = _session_pattern(payload["patch"]["pattern"])
            if command == "batch":
                for item in payload.get("items", []):
                    if isinstance(item.get("patch"), dict) and "pattern" in item["patch"]:
                        item["patch"]["pattern"] = _session_pattern(item["patch"]["pattern"])
        message["payload"] = payload
        return message

    if command in {"set", "spawn"}:
        channel = validate_channel_id(raw.get("channel"))
        patch = copy.deepcopy(raw.get("patch", {}))
        if not isinstance(patch, dict):
            raise ValidationError("session patch must be an object")
        if "pattern" in patch:
            patch["pattern"] = _session_pattern(patch["pattern"])
        if command == "spawn":
            patch.update({"active": True, "muted": False})
        message["command"] = "set"
        message["payload"] = {"channel": channel, "patch": patch}
    elif command == "batch":
        channels = raw.get("channels")
        if not isinstance(channels, dict):
            raise ValidationError("session batch requires a channels object")
        items = []
        for channel_text, raw_patch in channels.items():
            patch = copy.deepcopy(raw_patch)
            if not isinstance(patch, dict):
                raise ValidationError("each session batch patch must be an object")
            if "pattern" in patch:
                patch["pattern"] = _session_pattern(patch["pattern"])
            items.append({"channel": validate_channel_id(channel_text), "patch": patch})
        message["payload"] = {"items": items}
    elif command in {"mute", "unmute"}:
        message["command"] = "mute"
        message["payload"] = {"channel": validate_channel_id(raw.get("channel")), "muted": command == "mute"}
    elif command in {"clear", "kill", "restart"}:
        message["payload"] = {"channel": validate_channel_id(raw.get("channel"))}
    elif command == "tempo":
        message["payload"] = {"bpm": raw.get("bpm")}
    elif command == "master":
        message["payload"] = {"volume": raw.get("volume")}
    elif command == "deadline":
        message["payload"] = (
            {"cancel": True}
            if raw.get("cancel")
            else {"seconds": raw.get("seconds"), "deadline_fade": raw.get("deadline_fade", 3.0)}
        )
    elif command == "status":
        message["compact"] = bool(raw.get("compact", True))
        message["history"] = int(raw.get("history", 16))
    elif command == "history":
        if "after_id" in raw:
            message["after_id"] = raw["after_id"]
        message["limit"] = int(raw.get("limit", 64))
    elif command in {"ping", "panic", "stop"}:
        if command == "stop":
            message["payload"] = {}
    else:
        raise ValidationError(f"unknown session command {command!r}")
    return message


def command_session(args: argparse.Namespace) -> int:
    """Keep one socket open and exchange newline-delimited conductor commands."""
    state_dir = args.state_dir.expanduser().resolve()
    terminal_state = None
    terminal_fd = None
    if sys.stdin.isatty():
        # PTY canonical mode rejects lines around 1 KiB and emits BELs.  Cbreak
        # mode preserves newline-delimited input without imposing that terminal
        # line buffer, which is essential for multi-lane JSON batches.
        import termios
        import tty

        terminal_fd = sys.stdin.fileno()
        terminal_state = termios.tcgetattr(terminal_fd)
        tty.setcbreak(terminal_fd, termios.TCSANOW)
    try:
        with EngineConnection(state_dir, timeout=None) as connection:
            identity = connection.request({"command": "ping"})
            print(json.dumps({"ok": True, "session": "ready", "pid": identity["pid"]}, separators=(",", ":")), flush=True)
            for raw_line in sys.stdin:
                line = raw_line.strip()
                if not line or line.startswith("#"):
                    continue
                if line == "quit":
                    print('{"ok":true,"session":"closed","engine":"continues"}', flush=True)
                    break
                try:
                    request_data = json.loads(line)
                    if request_data.get("command") == "quit":
                        print('{"ok":true,"session":"closed","engine":"continues"}', flush=True)
                        break
                    response = connection.request(_normalize_session_request(request_data))
                except Exception as exc:
                    response = {"ok": False, "error": str(exc)}
                print(json.dumps(response, separators=(",", ":")), flush=True)
    finally:
        if terminal_state is not None and terminal_fd is not None:
            import termios

            termios.tcsetattr(terminal_fd, termios.TCSANOW, terminal_state)
    return 0


def command_history(args: argparse.Namespace) -> int:
    state_dir = args.state_dir.expanduser().resolve()
    try:
        response = request(
            state_dir,
            {"command": "history", "after_id": args.after_id, "limit": args.limit},
        )
        history = response["history"]
    except (OSError, RuntimeError):
        state_path = state_dir / STATE_NAME
        if not state_path.exists():
            raise RuntimeError("MCFA is not running and no saved history exists")
        history = json.loads(state_path.read_text(encoding="utf-8")).get("history", [])[-args.limit :]
    print(json.dumps(history, indent=2, sort_keys=True))
    return 0


def command_set(args: argparse.Namespace) -> int:
    patch: dict[str, Any] = {}
    for name in ("name", "active", "clock", "bpm", "volume", "pan", "step_beats", "random_seed", "muted"):
        value = getattr(args, name, None)
        if value is not None:
            patch[name] = value
    if args.pattern is not None and args.pattern_json is not None:
        raise ValidationError("use either --pattern or --pattern-json, not both")
    if args.pattern is not None:
        steps = parse_pattern(args.pattern)
        if args.length is not None:
            if args.length < len(steps):
                raise ValidationError("--length cannot be shorter than the supplied pattern")
            from .model import Step

            steps.extend(Step() for _ in range(args.length - len(steps)))
        patch["pattern"] = [step.public() for step in steps]
    elif args.pattern_json is not None:
        raw = json.loads(args.pattern_json)
        if not isinstance(raw, list):
            raise ValidationError("--pattern-json must be a JSON list")
        steps = pattern_from_json(raw)
        if args.length is not None:
            if args.length < len(steps):
                raise ValidationError("--length cannot be shorter than the supplied pattern")
            from .model import Step

            steps.extend(Step() for _ in range(args.length - len(steps)))
        patch["pattern"] = [step.public() for step in steps]
    elif args.length is not None:
        raise ValidationError("--length requires --pattern or --pattern-json")

    synth: dict[str, Any] = {}
    for name in ("waveform", "detune"):
        value = getattr(args, name, None)
        if value is not None:
            synth[name] = value
    envelope = _selected(args, ("attack", "decay", "sustain", "release"))
    filter_patch = {
        key: value
        for key, value in {
            "type": args.filter_type,
            "cutoff": args.cutoff,
            "resonance": args.resonance,
        }.items()
        if value is not None
    }
    effects = _selected(args, ("drive", "delay_mix", "delay_time", "delay_feedback", "reverb_mix"))
    modulation = {
        key: value
        for key, value in {
            "target": getattr(args, "mod_target", None),
            "waveform": getattr(args, "mod_waveform", None),
            "rate_hz": getattr(args, "mod_rate", None),
            "depth": getattr(args, "mod_depth", None),
        }.items()
        if value is not None
    }
    if envelope:
        synth["envelope"] = envelope
    if filter_patch:
        synth["filter"] = filter_patch
    if effects:
        synth["effects"] = effects
    if modulation:
        synth["modulation"] = modulation
    if synth:
        patch["synth"] = synth
    if not patch:
        raise ValidationError("set requires at least one channel option")
    response = _send_scheduled(args, "set", {"channel": args.channel, "patch": patch})
    _print_result(args, response, _scheduled_text(response))
    return 0


def command_simple_schedule(args: argparse.Namespace) -> int:
    if args.action == "mute":
        payload = {"channel": args.channel, "muted": True}
    elif args.action == "unmute":
        payload = {"channel": args.channel, "muted": False}
    elif args.action == "clear":
        payload = {"channel": args.channel}
    elif args.action in {"kill", "restart"}:
        payload = {"channel": args.channel}
    elif args.action == "tempo":
        payload = {"bpm": args.bpm}
    elif args.action == "master":
        payload = {"volume": args.volume}
    else:
        raise AssertionError(args.action)
    response = _send_scheduled(args, "mute" if args.action == "unmute" else args.action, payload)
    _print_result(args, response, _scheduled_text(response))
    return 0


def command_batch(args: argparse.Namespace) -> int:
    if bool(args.file) == bool(args.data):
        raise ValidationError("batch requires exactly one of --file or --data")
    raw = json.loads(Path(args.file).read_text(encoding="utf-8") if args.file else args.data)
    if isinstance(raw, dict) and "channels" in raw:
        channels = raw["channels"]
        if not isinstance(channels, dict):
            raise ValidationError("batch channels must be an object keyed by channel number")
        raw = [{"channel": int(channel), "patch": patch} for channel, patch in channels.items()]
    if not isinstance(raw, list):
        raise ValidationError("batch data must be a list or an object with a channels map")
    items: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            raise ValidationError("each batch item must be an object")
        patch = copy.deepcopy(item.get("patch", {}))
        if isinstance(patch.get("pattern"), str):
            patch["pattern"] = [step.public() for step in parse_pattern(patch["pattern"])]
        elif "pattern" in patch and isinstance(patch["pattern"], list) and patch["pattern"]:
            patch["pattern"] = [step.public() for step in pattern_from_json(patch["pattern"])]
        items.append({"channel": item.get("channel"), "patch": patch})
    response = _send_scheduled(args, "batch", {"items": items})
    _print_result(args, response, _scheduled_text(response))
    return 0


def command_deadline(args: argparse.Namespace) -> int:
    if args.cancel:
        payload = {"cancel": True}
    elif args.seconds is None:
        raise ValidationError("deadline requires SECONDS or --cancel")
    else:
        payload = {"seconds": args.seconds, "deadline_fade": args.deadline_fade}
    response = _send_scheduled(args, "deadline", payload)
    _print_result(args, response, _scheduled_text(response))
    return 0


def command_stop(args: argparse.Namespace) -> int:
    state_dir = args.state_dir.expanduser().resolve()
    response = request(
        state_dir,
        {"command": "stop", "payload": {}, "at": args.at, "fade": args.fade},
    )
    if not args.no_wait:
        in_beats = float(response.get("scheduled", {}).get("in_beats", 0.0))
        try:
            bpm = float(request(state_dir, {"command": "status"})["state"]["bpm"])
        except (OSError, RuntimeError, KeyError, ValueError):
            bpm = 120.0
        quantized_wait = in_beats * 60.0 / bpm
        _wait_for_exit(state_dir, max(quantized_wait + args.fade + 5.0, 5.0))
    _print_result(args, response, f"MCFA stop scheduled ({args.at}, {args.fade:g}s fade)")
    return 0


def command_panic(args: argparse.Namespace) -> int:
    state_dir = args.state_dir.expanduser().resolve()
    response = request(state_dir, {"command": "panic"})
    _wait_for_exit(state_dir, 3.0)
    _print_result(args, response, "PANIC: audio silenced immediately and engine stopped")
    return 0


def command_wait(args: argparse.Namespace) -> int:
    state_dir = args.state_dir.expanduser().resolve()
    started = time.monotonic()
    while ping(state_dir, timeout=0.5):
        if args.timeout is not None and time.monotonic() - started >= args.timeout:
            raise RuntimeError("wait timed out while MCFA was still running")
        time.sleep(min(0.25, args.interval))
    print("MCFA has stopped")
    return 0


def command_devices(args: argparse.Namespace) -> int:
    try:
        import sounddevice as sd
    except ImportError as exc:
        raise RuntimeError("sounddevice is not installed; run 'python3 -m pip install -e .'") from exc
    devices = sd.query_devices()
    if args.json:
        print(json.dumps([dict(device) for device in devices], indent=2, default=str))
    else:
        print(devices)
    return 0


def command_schema(_args: argparse.Namespace) -> int:
    schema = {
        "entropy_stamp": "one 128-bit SystemRandom hex stamp per engine run",
        "channels": f"integer 1..{MAX_CHANNELS}",
        "quantization": ["now", "next-step", "next-beat", "next-bar", "+Nbeats"],
        "pattern": {
            "compact": "C3 . C3+G3:0.7:0.5 . (note/chord:velocity:gate:probability)",
            "json_step": {"notes": ["C3", "E3"], "velocity": 0.8, "gate": 0.75, "probability": 1.0},
        },
        "channel_patch": {
            "name": "string",
            "active": "boolean (kill/restart lifecycle)",
            "muted": "boolean",
            "clock": sorted(CLOCK_MODES),
            "bpm": "20..400, used by free clocks",
            "volume": "0..1",
            "pan": "-1..1",
            "step_beats": "0.015625..16",
            "random_seed": "integer/0x hex seed, 'system' for SystemRandom entropy, or 'default'; status returns exact 0x hex",
            "pattern": "list of steps",
            "synth": {
                "waveform": sorted(WAVEFORMS),
                "detune": "-100..100 cents",
                "envelope": {"attack": "seconds", "decay": "seconds", "sustain": "0..1", "release": "seconds"},
                "filter": {"type": sorted(FILTER_TYPES), "cutoff": "20..20000 Hz", "resonance": "0..0.95"},
                "effects": {"drive": "0..1", "delay_mix": "0..1", "delay_time": "0.01..2 seconds", "delay_feedback": "0..0.95", "reverb_mix": "0..1"},
                "modulation": {
                    "target": sorted(MODULATION_TARGETS),
                    "waveform": sorted(MODULATION_WAVEFORMS),
                    "rate_hz": "0.01..40",
                    "depth": "0..1",
                },
            },
        },
        "session": {
            "transport": "newline-delimited JSON over one persistent socket",
            "commands": ["spawn", "set", "batch", "mute", "unmute", "clear", "kill", "restart", "status", "history", "tempo", "master", "deadline", "stop", "panic", "quit"],
        },
    }
    print(json.dumps(schema, indent=2, sort_keys=True))
    return 0


def command_logs(args: argparse.Namespace) -> int:
    path = args.state_dir.expanduser().resolve() / "engine.log"
    if not path.exists():
        raise RuntimeError(f"no engine log exists at {path}")
    print(_tail(path, args.lines))
    return 0


def _send_scheduled(args: argparse.Namespace, command: str, payload: dict[str, Any]) -> dict[str, Any]:
    return request(
        args.state_dir.expanduser().resolve(),
        {"command": command, "payload": payload, "at": args.at, "fade": args.fade},
    )


def _selected(args: argparse.Namespace, names: tuple[str, ...]) -> dict[str, Any]:
    return {name: getattr(args, name) for name in names if getattr(args, name, None) is not None}


def _scheduled_text(response: dict[str, Any]) -> str:
    scheduled = response["scheduled"]
    target = scheduled["at_beat"]
    return f"Scheduled {scheduled['kind']} at beat {target:g} ({scheduled['fade_seconds']:g}s transition)"


def _print_result(args: argparse.Namespace, response: dict[str, Any], text: str) -> None:
    if getattr(args, "json", False):
        print(json.dumps(response, indent=2, sort_keys=True))
    else:
        print(text)


def _wait_for_exit(state_dir: Path, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if ping(state_dir) is None:
            return
        time.sleep(0.05)
    raise RuntimeError("engine did not exit before the safety timeout; use 'mcfa panic'")


def _tail(path: Path, lines: int) -> str:
    try:
        return "\n".join(path.read_text(encoding="utf-8", errors="replace").splitlines()[-lines:])
    except OSError:
        return ""


def _pattern_summary(pattern: list[dict[str, Any]], limit: int = 12) -> str:
    tokens = []
    for step in pattern[:limit]:
        notes = step.get("notes", [])
        tokens.append("+".join(notes) if notes else ".")
    if len(pattern) > limit:
        tokens.append("…")
    return " ".join(tokens) if tokens else "(empty)"


def _print_status_table(state: dict[str, Any], live: bool) -> None:
    transport = state["transport"]
    mode = "RUNNING" if live and state.get("running") else "STOPPED (saved state)"
    print(
        f"MCFA {mode} | {state['backend']} | {state['bpm']:g} BPM | "
        f"bar {transport['bar']} beat {transport['beat_in_bar'] + 1:.2f} | master {state['master_volume']:.2f}"
    )
    deadline = state.get("deadline", {})
    if deadline.get("active"):
        print(f"Deadline: {deadline['seconds_remaining']:.2f}s remaining, {deadline['fade_seconds']:.2f}s final fade")
    if state.get("scheduled"):
        print(f"Scheduled transitions: {len(state['scheduled'])}")
    print("CH  M  VOL   PAN   WAVE      FILTER             LOOP          VOICES  PATTERN")
    for channel in state["channels"]:
        synth = channel["synth"]
        filter_data = synth["filter"]
        runtime = channel["runtime"]
        muted = "M" if channel["muted"] else "-"
        loop = f"{channel['loop_steps']}x{channel['step_beats']:g}b"
        filter_text = f"{filter_data['type'][:4]} {filter_data['cutoff']:>6.0f}"
        print(
            f"{channel['id']:>2}  {muted}  {channel['volume']:.2f}  {channel['pan']:+.2f}  "
            f"{synth['waveform']:<8}  {filter_text:<17}  {loop:<12}  "
            f"{runtime['active_voices']:^6}  {_pattern_summary(channel['pattern'])}"
        )


def _print_channel_detail(channel: dict[str, Any], live: bool) -> None:
    state = "live" if live else "saved"
    print(f"Channel {channel['id']} ({state}) {channel['name'] or '(unnamed)'}")
    print(json.dumps(channel, indent=2, sort_keys=True))


def _print_compact_status(state: dict[str, Any], live: bool) -> None:
    label = "RUNNING" if live and state["running"] else "STOPPED"
    deadline = state.get("deadline", {})
    remaining = deadline.get("seconds_remaining")
    suffix = f" | deadline {remaining:.1f}s" if remaining is not None and deadline.get("active") else ""
    print(f"MCFA {label} | {state['backend']} | {state['bpm']:g} master BPM{suffix}")
    print("LANE  A  M  CLOCK       LOOP       VOL   PAN   MOD         LEVEL    NAME")
    for channel in state["channels"]:
        active = "Y" if channel["active"] else "-"
        muted = "M" if channel["muted"] else "-"
        clock = f"{channel['clock']}@{channel['bpm']:g}"
        loop = f"{channel['loop_steps']}x{channel['step_beats']:g}"
        print(
            f"{channel['id']:>4}  {active}  {muted}  {clock:<10}  {loop:<9}  "
            f"{channel['volume']:.2f}  {channel['pan']:+.2f}  {channel['modulation']:<10}  "
            f"{channel['level']['rms']:.4f}  {channel['name'] or '(unnamed)'}"
        )
    print(f"History entries shown: {len(state.get('history', []))} | underruns: {state['health']['underruns']}")


def _add_schedule_options(parser: argparse.ArgumentParser, default_fade: float = 0.05) -> None:
    parser.add_argument("--at", default="now", help="now, next-step, next-beat, next-bar, or +Nbeats")
    parser.add_argument("--fade", type=float, default=default_fade, help="parameter transition/fade seconds")
    parser.add_argument("--json", action="store_true", help="print the engine response as JSON")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mcfa",
        description="Control the persistent Metamodern Classical for Agents noise instrument",
    )
    parser.add_argument("--state-dir", type=Path, default=default_state_dir(), help="runtime state directory")
    subparsers = parser.add_subparsers(dest="action", required=True)

    start = subparsers.add_parser("start", help="start the persistent engine")
    start.add_argument("--backend", choices=("sounddevice", "null"), default="sounddevice")
    start.add_argument("--bpm", type=float, default=120.0)
    start.add_argument("--sample-rate", type=int, default=44100)
    start.add_argument("--block-size", type=int, default=1024)
    start.add_argument("--master-volume", type=float, default=0.8)
    start.add_argument("--duration", type=float, help="automatic stop deadline in seconds")
    start.add_argument("--deadline-fade", type=float, default=3.0)
    start.add_argument("--device", help="sounddevice output device name or index")
    start.add_argument("--startup-timeout", type=float, default=5.0, help=argparse.SUPPRESS)
    start.add_argument("--json", action="store_true")
    start.set_defaults(func=command_start)

    status = subparsers.add_parser("status", help="inspect all state or one channel")
    status.add_argument("channel", nargs="?", type=int, choices=range(1, MAX_CHANNELS + 1))
    status.add_argument("--compact", action="store_true", help="omit full patterns and synth details")
    status.add_argument("--history", type=int, default=16, help="history entries included with compact state")
    status.add_argument("--json", action="store_true")
    status.set_defaults(func=command_status)

    set_parser = subparsers.add_parser("set", help="change a channel without stopping playback")
    set_parser.add_argument("channel", type=int, choices=range(1, MAX_CHANNELS + 1))
    set_parser.add_argument("--name")
    active_group = set_parser.add_mutually_exclusive_group()
    active_group.add_argument("--active", action="store_true", default=None)
    active_group.add_argument("--inactive", action="store_false", dest="active")
    set_parser.add_argument("--clock", choices=sorted(CLOCK_MODES))
    set_parser.add_argument("--lane-bpm", type=float, dest="bpm")
    set_parser.add_argument("--pattern", help="steps such as 'C3 . C3+G3:0.7:0.5 .'")
    set_parser.add_argument("--pattern-json", help="explicit JSON step list")
    set_parser.add_argument("--length", type=int, choices=range(1, 257), help="pad the supplied pattern to this loop length")
    set_parser.add_argument("--step-beats", type=float)
    set_parser.add_argument("--random-seed", help="integer seed, 'system', or 'default'")
    set_parser.add_argument("--volume", type=float)
    set_parser.add_argument("--pan", type=float)
    mute_group = set_parser.add_mutually_exclusive_group()
    mute_group.add_argument("--muted", action="store_true", default=None)
    mute_group.add_argument("--unmuted", action="store_false", dest="muted")
    set_parser.add_argument("--waveform", choices=sorted(WAVEFORMS))
    set_parser.add_argument("--detune", type=float)
    set_parser.add_argument("--filter", dest="filter_type", choices=sorted(FILTER_TYPES))
    set_parser.add_argument("--cutoff", type=float)
    set_parser.add_argument("--resonance", type=float)
    set_parser.add_argument("--attack", type=float)
    set_parser.add_argument("--decay", type=float)
    set_parser.add_argument("--sustain", type=float)
    set_parser.add_argument("--release", type=float)
    set_parser.add_argument("--drive", type=float)
    set_parser.add_argument("--delay-mix", type=float)
    set_parser.add_argument("--delay-time", type=float)
    set_parser.add_argument("--delay-feedback", type=float)
    set_parser.add_argument("--reverb-mix", type=float)
    set_parser.add_argument("--mod-target", choices=sorted(MODULATION_TARGETS))
    set_parser.add_argument("--mod-waveform", choices=sorted(MODULATION_WAVEFORMS))
    set_parser.add_argument("--mod-rate", type=float, help="lane LFO rate in Hz")
    set_parser.add_argument("--mod-depth", type=float, help="lane LFO depth 0..1")
    _add_schedule_options(set_parser)
    set_parser.set_defaults(func=command_set)

    for action, help_text in (
        ("mute", "fade a lane to mute while its clock continues"),
        ("unmute", "fade a muted lane back in"),
        ("clear", "clear a lane pattern"),
        ("kill", "immediately kill one lane and its effect memory"),
        ("restart", "restart a killed lane from the beginning"),
    ):
        sub = subparsers.add_parser(action, help=help_text)
        sub.add_argument("channel", type=int, choices=range(1, MAX_CHANNELS + 1))
        _add_schedule_options(sub)
        sub.set_defaults(func=command_simple_schedule)

    tempo = subparsers.add_parser("tempo", help="change transport tempo")
    tempo.add_argument("bpm", type=float)
    _add_schedule_options(tempo, 0.0)
    tempo.set_defaults(func=command_simple_schedule)

    master = subparsers.add_parser("master", help="change master volume")
    master.add_argument("volume", type=float)
    _add_schedule_options(master)
    master.set_defaults(func=command_simple_schedule)

    batch = subparsers.add_parser("batch", help="apply multiple channel patches atomically")
    batch.add_argument("--file", type=Path)
    batch.add_argument("--data", help="inline JSON list or channels map")
    _add_schedule_options(batch)
    batch.set_defaults(func=command_batch)

    deadline = subparsers.add_parser("deadline", help="set or cancel Python-owned automatic stop")
    deadline.add_argument("seconds", nargs="?", type=float)
    deadline.add_argument("--deadline-fade", type=float, default=3.0)
    deadline.add_argument("--cancel", action="store_true")
    _add_schedule_options(deadline, 0.0)
    deadline.set_defaults(func=command_deadline)

    stop = subparsers.add_parser("stop", help="gracefully fade and stop the engine")
    stop.add_argument("--at", default="now")
    stop.add_argument("--fade", type=float, default=2.0)
    stop.add_argument("--no-wait", action="store_true")
    stop.add_argument("--json", action="store_true")
    stop.set_defaults(func=command_stop)

    panic = subparsers.add_parser("panic", help="immediately silence and stop the engine")
    panic.add_argument("--json", action="store_true")
    panic.set_defaults(func=command_panic)

    wait = subparsers.add_parser("wait", help="wait for a deadline or stop to finish")
    wait.add_argument("--timeout", type=float)
    wait.add_argument("--interval", type=float, default=0.25)
    wait.set_defaults(func=command_wait)

    session = subparsers.add_parser("session", help="open one persistent NDJSON conductor connection")
    session.set_defaults(func=command_session)

    history = subparsers.add_parser("history", help="inspect the persistent decision/event history")
    history.add_argument("--after-id", type=int)
    history.add_argument("--limit", type=int, default=64)
    history.set_defaults(func=command_history)

    devices = subparsers.add_parser("devices", help="list available CoreAudio devices")
    devices.add_argument("--json", action="store_true")
    devices.set_defaults(func=command_devices)

    schema = subparsers.add_parser("schema", help="print the channel/pattern command schema")
    schema.set_defaults(func=command_schema)

    logs = subparsers.add_parser("logs", help="show the end of the engine log")
    logs.add_argument("--lines", type=int, default=50)
    logs.set_defaults(func=command_logs)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except (ValidationError, RuntimeError, OSError, json.JSONDecodeError) as exc:
        print(f"mcfa: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
