"""Persistent MCFA process, audio backends, and local Unix-socket server."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import signal
import socketserver
import sys
import threading
import time
import traceback
from typing import Any

from . import __version__
from .model import ValidationError
from .synth import SynthEngine


SOCKET_NAME = "engine.sock"
PID_NAME = "engine.pid"
STATE_NAME = "state.json"


class NullBackend:
    """Real-time silent backend used for tests, development, and headless control."""

    name = "null"

    def __init__(self, engine: SynthEngine, block_size: int) -> None:
        self.engine = engine
        self.block_size = block_size
        self.thread: threading.Thread | None = None

    def start(self) -> None:
        self.thread = threading.Thread(target=self._run, name="mcfa-null-audio", daemon=True)
        self.thread.start()

    def _run(self) -> None:
        block_seconds = self.block_size / self.engine.sample_rate
        target = time.monotonic()
        while self.engine.running:
            rendered_at = time.monotonic()
            self.engine.render(self.block_size)
            # A null backend has no hardware buffer to underflow.  Count only a
            # renderer that actually takes longer than its audio block; ordinary
            # OS wake-up jitter after sleep is not an audio failure.
            if time.monotonic() - rendered_at > block_seconds:
                self.engine.underruns += 1
            target += block_seconds
            delay = target - time.monotonic()
            if delay > 0:
                time.sleep(delay)
            elif delay < -block_seconds:
                target = time.monotonic()

    def close(self) -> None:
        if self.thread and self.thread is not threading.current_thread():
            self.thread.join(timeout=1.0)


class SoundDeviceBackend:
    """CoreAudio output through sounddevice's blocking raw-buffer stream."""

    name = "sounddevice"

    def __init__(self, engine: SynthEngine, block_size: int, device: str | int | None = None) -> None:
        self.engine = engine
        self.block_size = block_size
        if isinstance(device, str) and device.lstrip("-").isdigit():
            self.device = int(device)
        else:
            self.device = device
        self.stream: Any = None
        self.error: str | None = None
        self.thread: threading.Thread | None = None

    def start(self) -> None:
        try:
            import sounddevice as sd
        except ImportError as exc:
            raise RuntimeError(
                "sounddevice is not installed; run 'python3 -m pip install -e .' "
                "or use --backend null for a silent engine"
            ) from exc

        self.stream = sd.RawOutputStream(
            samplerate=self.engine.sample_rate,
            blocksize=self.block_size,
            device=self.device,
            channels=2,
            dtype="float32",
            # MCFA is controlled at phrase/gesture timescales. A resilient
            # CoreAudio buffer matters more than single-digit millisecond input
            # latency, especially while control/status traffic is active.
            latency="high",
        )
        self.stream.start()
        self.thread = threading.Thread(target=self._run, name="mcfa-coreaudio", daemon=True)
        self.thread.start()

    def _run(self) -> None:
        try:
            while self.engine.running:
                rendered = self.engine.render(self.block_size)
                if self.stream.write(rendered.tobytes()):
                    self.engine.underruns += 1
        except Exception as exc:
            self.error = f"{type(exc).__name__}: {exc}"
            with self.engine.lock:
                self.engine.stop_reason = f"audio-error: {self.error}"
                self.engine.master.set(0.0, 0)
                self.engine.running = False

    def close(self) -> None:
        if self.stream is not None:
            if self.thread and self.thread is not threading.current_thread():
                self.thread.join(timeout=1.0)
            try:
                self.stream.stop()
            except Exception:
                pass
            self.stream.close()


class ThreadingUnixServer(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True
    allow_reuse_address = True


class ControlHandler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        # One connection may carry an entire performance as newline-delimited
        # JSON.  Ordinary one-shot CLI calls still send one line and close.
        self.request.settimeout(None)
        while True:
            raw = self.rfile.readline(1_048_577)
            if not raw:
                return
            if len(raw) > 1_048_576:
                response = {"ok": False, "error": "request exceeds 1 MiB"}
            else:
                try:
                    request = json.loads(raw)
                    response = self.server.controller.handle_request(request)  # type: ignore[attr-defined]
                except (ValidationError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
                    response = {"ok": False, "error": str(exc)}
                except Exception as exc:
                    traceback.print_exc()
                    response = {"ok": False, "error": f"internal engine error: {type(exc).__name__}: {exc}"}
            try:
                self.wfile.write(json.dumps(response, separators=(",", ":")).encode() + b"\n")
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                return


class Controller:
    def __init__(self, engine: SynthEngine) -> None:
        self.engine = engine

    def handle_request(self, request: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(request, dict):
            raise ValidationError("request must be a JSON object")
        command = request.get("command")
        if command == "ping":
            return {"ok": True, "pid": os.getpid(), "version": __version__, "running": self.engine.running}
        if command == "status":
            if request.get("compact"):
                return {"ok": True, "state": self.engine.compact_status(request.get("history", 16))}
            return {"ok": True, "state": self.engine.status()}
        if command == "history":
            return {
                "ok": True,
                "history": self.engine.history_since(request.get("after_id"), request.get("limit", 64)),
            }
        if command == "panic":
            self.engine.panic()
            return {"ok": True, "panic": True}
        if command in {"set", "clear", "mute", "kill", "restart", "batch", "tempo", "master", "deadline", "stop"}:
            payload = request.get("payload", {})
            if not isinstance(payload, dict):
                raise ValidationError("payload must be a JSON object")
            scheduled = self.engine.schedule(
                command,
                payload,
                at=str(request.get("at", "now")),
                fade=float(request.get("fade", 0.05)),
            )
            return {"ok": True, "scheduled": scheduled}
        raise ValidationError(f"unknown command {command!r}")


def write_json_atomic(path: Path, data: dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def run_daemon(args: argparse.Namespace) -> int:
    state_dir = Path(args.state_dir).expanduser().resolve()
    state_dir.mkdir(parents=True, exist_ok=True)
    socket_path = state_dir / SOCKET_NAME
    pid_path = state_dir / PID_NAME
    state_path = state_dir / STATE_NAME
    if len(os.fsencode(socket_path)) >= 100:
        raise RuntimeError(f"state directory path is too long for a Unix socket: {state_dir}")
    if socket_path.exists():
        socket_path.unlink()

    engine = SynthEngine(
        bpm=args.bpm,
        sample_rate=args.sample_rate,
        master_volume=args.master_volume,
        backend_name=args.backend,
        duration=args.duration,
        deadline_fade=args.deadline_fade,
    )
    if args.backend == "null":
        backend: NullBackend | SoundDeviceBackend = NullBackend(engine, args.block_size)
    else:
        backend = SoundDeviceBackend(engine, args.block_size, args.device)
    controller = Controller(engine)
    server: ThreadingUnixServer | None = None

    def stop_from_signal(_signum: int, _frame: Any) -> None:
        engine.request_stop(0.25)

    signal.signal(signal.SIGTERM, stop_from_signal)
    signal.signal(signal.SIGINT, stop_from_signal)

    try:
        backend.start()
        engine.backend_name = backend.name
        server = ThreadingUnixServer(str(socket_path), ControlHandler)
        server.controller = controller  # type: ignore[attr-defined]
        server_thread = threading.Thread(target=server.serve_forever, name="mcfa-control", daemon=True)
        server_thread.start()
        pid_path.write_text(f"{os.getpid()}\n", encoding="ascii")
        last_state_write = 0.0
        while engine.running:
            now = time.monotonic()
            if now - last_state_write >= 1.0:
                write_json_atomic(state_path, engine.status())
                last_state_write = now
            time.sleep(0.03)
        write_json_atomic(state_path, engine.status())
        return 0
    finally:
        if server is not None:
            server.shutdown()
            server.server_close()
        backend.close()
        try:
            if socket_path.exists():
                socket_path.unlink()
        except OSError:
            pass
        try:
            if pid_path.exists() and pid_path.read_text(encoding="ascii").strip() == str(os.getpid()):
                pid_path.unlink()
        except OSError:
            pass


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m mcfa.daemon")
    parser.add_argument("--state-dir", required=True)
    parser.add_argument("--backend", choices=("sounddevice", "null"), default="sounddevice")
    parser.add_argument("--bpm", type=float, default=120.0)
    parser.add_argument("--sample-rate", type=int, default=44100)
    parser.add_argument("--block-size", type=int, default=1024)
    parser.add_argument("--master-volume", type=float, default=0.8)
    parser.add_argument("--duration", type=float)
    parser.add_argument("--deadline-fade", type=float, default=3.0)
    parser.add_argument("--device")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return run_daemon(args)
    except Exception as exc:
        traceback.print_exc()
        print(f"MCFA engine failed: {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
