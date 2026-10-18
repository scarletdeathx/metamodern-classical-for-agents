"""Eshkol entropy provider for MCFA control-plane use.

Pulls draws from a local drawd instance (TCP 127.0.0.1:18751 or Unix
socket /tmp/eshkol-drawd.sock) using drawd's v1 protocol:

    -> {"backend": "<name>", "n": <bytes>}\n
    <- 4-byte big-endian length, then exactly <n> random bytes

Acquisition happens on the control plane only; the audio renderer never
performs entropy I/O. A failed drawd connection raises visibly -- there
is no silent fallback to SystemRandom.
"""

from __future__ import annotations

import json
import platform
import socket
import struct
from typing import Any

from .base import EntropyChunk, EntropyProviderError


MAX_READ_BYTES = 1 << 20
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 18751
DEFAULT_SOCKET = "/tmp/eshkol-drawd.sock"
DEFAULT_BACKEND = "synthetic"
_ERR_LEN = 0xFFFFFFFF


def _read_exact(sock: socket.socket, count: int) -> bytes:
    buf = bytearray()
    while len(buf) < count:
        chunk = sock.recv(count - len(buf))
        if not chunk:
            raise EntropyProviderError("drawd closed the connection mid-draw")
        buf.extend(chunk)
    return bytes(buf)


def draw_from_drawd(
    count: int,
    backend: str = DEFAULT_BACKEND,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    socket_path: str | None = DEFAULT_SOCKET,
    timeout: float = 5.0,
) -> bytes:
    """Pull exactly `count` bytes from drawd. Raises on any failure."""
    if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= MAX_READ_BYTES:
        raise ValueError(f"count must be an integer between 1 and {MAX_READ_BYTES}")
    request = json.dumps({"backend": backend, "n": count}).encode() + b"\n"

    # Prefer the Unix socket; fall back to TCP.
    last_error: Exception | None = None
    if socket_path:
        try:
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.settimeout(timeout)
            sock.connect(socket_path)
        except OSError as exc:
            last_error = exc
            sock = None  # type: ignore[assignment]
        else:
            last_error = None
    else:
        sock = None  # type: ignore[assignment]

    if sock is None:
        try:
            sock = socket.create_connection((host, port), timeout=timeout)
        except OSError as exc:
            raise EntropyProviderError(
                f"cannot reach drawd at {socket_path or f'{host}:{port}'}: {exc}"
                + (f" (socket error: {last_error})" if last_error else "")
            ) from exc

    try:
        sock.sendall(request)
        (length,) = struct.unpack(">I", _read_exact(sock, 4))
        if length == _ERR_LEN:
            raise EntropyProviderError("drawd reported an error for this draw")
        if length != count:
            raise EntropyProviderError(
                f"drawd returned {length} bytes, expected {count}"
            )
        return _read_exact(sock, length)
    finally:
        sock.close()


class EshkolEntropyProvider:
    """Bounded Eshkol draws via local drawd, shaped as MCFA EntropyChunks."""

    def __init__(
        self,
        backend: str = DEFAULT_BACKEND,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
        socket_path: str | None = DEFAULT_SOCKET,
        timeout: float = 5.0,
    ) -> None:
        self.backend = backend
        self.host = host
        self.port = port
        self.socket_path = socket_path
        self.timeout = timeout

    def read(self, count: int) -> EntropyChunk:
        data = draw_from_drawd(
            count,
            backend=self.backend,
            host=self.host,
            port=self.port,
            socket_path=self.socket_path,
            timeout=self.timeout,
        )
        return EntropyChunk(
            data=data,
            provider=f"eshkol-{self.backend}",
            execution="local-drawd",
            entropy_origin=f"eshkol-backend-{self.backend}",
            engine_version=platform.release(),
            source_revision="drawd-v1",
            physical_qpu=False,
        )

    def health(self) -> dict[str, Any]:
        try:
            draw_from_drawd(
                1,
                backend=self.backend,
                host=self.host,
                port=self.port,
                socket_path=self.socket_path,
                timeout=2.0,
            )
        except EntropyProviderError as exc:
            return {
                "status": "unavailable",
                "provider": f"eshkol-{self.backend}",
                "execution": "local-drawd",
                "error": str(exc),
                "network_required": False,
            }
        return {
            "status": "ready",
            "provider": f"eshkol-{self.backend}",
            "execution": "local-drawd",
            "entropy_origin": f"eshkol-backend-{self.backend}",
            "physical_qpu": False,
            "network_required": False,
        }

    def close(self) -> None:
        return None


def read_eshkol_entropy(count: int, backend: str = DEFAULT_BACKEND) -> EntropyChunk:
    """One-shot helper mirroring providers.tsotchke.read_tsotchke_entropy."""
    return EshkolEntropyProvider(backend=backend).read(count)
