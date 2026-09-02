"""Nonblocking entropy reservoir shared by future streaming providers.

Provider reads happen on a producer thread or explicitly on the control plane.
The real-time consumer surface, :meth:`take`, only copies already-buffered bytes
and reports starvation rather than calling a provider or waiting for I/O.
"""

from __future__ import annotations

import hashlib
import threading
import time
from typing import Any, Protocol

from .base import EntropyChunk, EntropyProviderError


class ChunkProvider(Protocol):
    def read(self, count: int) -> EntropyChunk: ...


class EntropyReservoir:
    """Bounded single-producer reservoir with a nonblocking consumer API."""

    def __init__(
        self,
        provider: ChunkProvider,
        *,
        capacity: int = 262_144,
        refill_size: int = 65_536,
        low_watermark: int | None = None,
        retry_seconds: float = 0.05,
        close_provider: bool = False,
    ) -> None:
        if isinstance(capacity, bool) or not isinstance(capacity, int) or capacity < 1:
            raise ValueError("capacity must be a positive integer")
        if isinstance(refill_size, bool) or not isinstance(refill_size, int) or not 1 <= refill_size <= capacity:
            raise ValueError("refill_size must be between 1 and capacity")
        watermark = capacity // 2 if low_watermark is None else low_watermark
        if isinstance(watermark, bool) or not isinstance(watermark, int) or not 0 <= watermark < capacity:
            raise ValueError("low_watermark must be between 0 and capacity - 1")
        if retry_seconds <= 0:
            raise ValueError("retry_seconds must be positive")

        self.provider = provider
        self.capacity = capacity
        self.refill_size = refill_size
        self.low_watermark = watermark
        self.retry_seconds = float(retry_seconds)
        self.close_provider = bool(close_provider)
        self._buffer = bytearray()
        self._condition = threading.Condition()
        self._stop = False
        self._thread: threading.Thread | None = None
        self._digest = hashlib.sha256()
        self._generated = 0
        self._requested = 0
        self._delivered = 0
        self._underflows = 0
        self._missing = 0
        self._refills = 0
        self._failures = 0
        self._last_error: str | None = None
        self._last_chunk: dict[str, Any] | None = None

    def start(self) -> None:
        """Start one background producer; repeated calls are harmless."""
        with self._condition:
            if self._stop:
                raise RuntimeError("closed entropy reservoir cannot be restarted")
            if self._thread is not None and self._thread.is_alive():
                return
            self._thread = threading.Thread(target=self._run, name="mcfa-entropy-reservoir", daemon=True)
            self._thread.start()

    def refill_once(self) -> bool:
        """Perform at most one provider read; call only off the audio thread."""
        with self._condition:
            if self._stop:
                return False
            count = min(self.refill_size, self.capacity - len(self._buffer))
        if count <= 0:
            return False
        try:
            chunk = self.provider.read(count)
            if not isinstance(chunk, EntropyChunk):
                raise EntropyProviderError("provider returned a non-EntropyChunk value")
            if len(chunk.data) != count:
                raise EntropyProviderError(f"provider returned {len(chunk.data)} bytes; expected {count}")
        except Exception as exc:
            with self._condition:
                self._failures += 1
                self._last_error = f"{type(exc).__name__}: {exc}"
                self._condition.notify_all()
            return False

        with self._condition:
            # Capacity can only shrink between the request and this append if a
            # future implementation adds explicit resizing. Keep the bound
            # nevertheless, so this remains safe if that feature arrives.
            accepted = chunk.data[: self.capacity - len(self._buffer)]
            self._buffer.extend(accepted)
            self._digest.update(accepted)
            self._generated += len(accepted)
            self._refills += 1
            self._last_error = None
            self._last_chunk = chunk.provenance()
            self._condition.notify_all()
        return bool(accepted)

    def _run(self) -> None:
        while True:
            with self._condition:
                self._condition.wait_for(lambda: self._stop or len(self._buffer) <= self.low_watermark)
                if self._stop:
                    return
            if not self.refill_once():
                with self._condition:
                    if not self._stop:
                        self._condition.wait(timeout=self.retry_seconds)

    def warm(self, minimum: int | None = None, *, timeout: float = 1.0) -> bool:
        """Wait on the control plane for an initial safe amount of buffered data."""
        target = self.low_watermark + 1 if minimum is None else minimum
        if isinstance(target, bool) or not isinstance(target, int) or not 0 <= target <= self.capacity:
            raise ValueError("minimum must be between 0 and capacity")
        self.start()
        deadline = time.monotonic() + max(0.0, float(timeout))
        with self._condition:
            while len(self._buffer) < target and not self._stop:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                self._condition.wait(timeout=remaining)
            return len(self._buffer) >= target

    def take(self, count: int) -> bytes | None:
        """Copy buffered bytes immediately, returning ``None`` on starvation."""
        if isinstance(count, bool) or not isinstance(count, int) or not 0 <= count <= self.capacity:
            raise ValueError("count must be between 0 and capacity")
        with self._condition:
            self._requested += count
            if len(self._buffer) < count:
                self._underflows += 1
                self._missing += count - len(self._buffer)
                self._condition.notify_all()
                return None
            result = bytes(self._buffer[:count])
            del self._buffer[:count]
            self._delivered += count
            if len(self._buffer) <= self.low_watermark:
                self._condition.notify_all()
            return result

    def status(self) -> dict[str, Any]:
        with self._condition:
            return {
                "status": "closed" if self._stop else ("starved" if self._underflows else "ready"),
                "capacity_bytes": self.capacity,
                "available_bytes": len(self._buffer),
                "low_watermark_bytes": self.low_watermark,
                "generated_bytes": self._generated,
                "requested_bytes": self._requested,
                "delivered_bytes": self._delivered,
                "underflows": self._underflows,
                "missing_bytes": self._missing,
                "refills": self._refills,
                "provider_failures": self._failures,
                "last_error": self._last_error,
                "stream_sha256": self._digest.hexdigest(),
                "last_chunk": self._last_chunk,
            }

    def close(self, *, timeout: float = 1.0) -> None:
        with self._condition:
            if self._stop:
                return
            self._stop = True
            self._condition.notify_all()
            thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=max(0.0, float(timeout)))
        if self.close_provider:
            close = getattr(self.provider, "close", None)
            if callable(close):
                close()

    def __enter__(self) -> "EntropyReservoir":
        self.start()
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        self.close()
