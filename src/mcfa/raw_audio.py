"""Raw-entropy audio: entropy bytes played directly as PCM, with no DSP.

A moonlab-backed take on harshnoise.social's OWIE easter egg (4 s of
crypto.getRandomValues bytes as unsigned 8-bit samples, sample = b/128 - 1,
gain 0.5, looped). Here the buffer is never looped: a fill-ahead reservoir
keeps pulling fresh entropy from any MCFA source.

Sample mapping (the only processing applied):
  bits=8:  sample = (b / 128 - 1) * gain, written as u8 = round(128 + 127.5*sample)
           clamped to 0..255 (gain 1.0 writes the byte unchanged)
  bits=16: sample = (int16_le(b0, b1) / 32768) * gain, written as s16le
           (gain 1.0 writes the byte pair unchanged)

This module never opens an audio device. Rendering produces WAV files only.
"""

from __future__ import annotations

from array import array
import hashlib
import json
import sys
import time
import wave
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Iterator, Iterable

from .providers.base import EntropyChunk, EntropyProviderError
from .providers.reservoir import EntropyReservoir

DEFAULT_SOURCE = "eshkol-local:moonlab"
# moonlab through drawd measured ~111-131 KB/s on the M-series Mac (2026-10-17)
# against 96 KB/s needed for 16-bit 48 kHz mono. Keep ~10 s of cushion.
DEFAULT_CAPACITY = 2 * 1024 * 1024
DEFAULT_REFILL = 65_536
DEFAULT_WARM = 1024 * 1024
BLOCK_FRAMES = 4800  # 100 ms at 48 kHz


@dataclass(frozen=True)
class RawFormat:
    rate: int = 48_000
    bits: int = 16
    channels: int = 1
    gain: float = 0.5

    def __post_init__(self) -> None:
        if self.bits not in (8, 16):
            raise ValueError("bits must be 8 or 16")
        if not 8_000 <= int(self.rate) <= 192_000:
            raise ValueError("rate must be 8000..192000")
        if not 1 <= int(self.channels) <= 8:
            raise ValueError("channels must be 1..8")
        if not 0.0 <= float(self.gain) <= 1.0:
            raise ValueError("gain must be 0..1")

    @property
    def bytes_per_frame(self) -> int:
        return self.bits // 8 * self.channels

    @property
    def bytes_per_second(self) -> int:
        return self.rate * self.bytes_per_frame


def map_u8(raw: bytes, gain: float) -> bytes:
    """OWIE mapping: sample = (b/128 - 1) * gain, re-encoded as u8 PCM."""
    if gain == 1.0:
        return bytes(raw)
    out = bytearray(len(raw))
    for i, b in enumerate(raw):
        v = round(128 + 127.5 * ((b / 128.0 - 1.0) * gain))
        out[i] = 0 if v < 0 else 255 if v > 255 else v
    return bytes(out)


def map_s16(raw: bytes, gain: float) -> bytes:
    """Byte pairs as little-endian int16, scaled by gain, re-encoded s16le."""
    if len(raw) % 2:
        raise ValueError("16-bit mapping needs an even byte count")
    if gain == 1.0:
        return bytes(raw)
    samples = array("h")
    samples.frombytes(raw)
    if sys.byteorder != "little":
        samples.byteswap()
    scaled = array("h", (max(-32768, min(32767, round(s * gain))) for s in samples))
    if sys.byteorder != "little":
        scaled.byteswap()
    return scaled.tobytes()


def map_pcm(raw: bytes, fmt: RawFormat) -> bytes:
    return map_u8(raw, fmt.gain) if fmt.bits == 8 else map_s16(raw, fmt.gain)


class _ChunkSource:
    """Adapts a source spec (or RNGoddess mixer) to the reservoir's read()."""

    def __init__(self, sources: list[str] | None, rngoddess: bool) -> None:
        from .providers.mixer import RNGoddessMixer, default_reader, normalize_sources, parse_source

        self.mixer = None
        if rngoddess:
            self.mixer = RNGoddessMixer(sources, label="mcfa/v2/rngoddess/raw-audio")
            self.sources = self.mixer.sources
            self._read = self.mixer.read
            self.manifests: list[dict[str, Any]] = []
        else:
            specs = normalize_sources(sources or [DEFAULT_SOURCE])
            if len(specs) != 1 or specs[0].endswith("?"):
                raise ValueError("without --rngoddess give exactly one required --source")
            self.sources = specs
            base, backend, _ = parse_source(specs[0])
            if base == "eshkol-local" and backend is None:
                from .providers.eshkol import DEFAULT_BACKEND
                backend = DEFAULT_BACKEND
                self.sources = [f"eshkol-local:{backend}"]
            self._read = default_reader(base, backend)
            self.manifests = []

    def read(self, count: int) -> EntropyChunk:
        chunk = self._read(count)
        if self.mixer is not None:
            self.manifests.append(self.mixer.provenance())
        return chunk


class RawEntropyStream:
    """Iterator of PCM blocks fed by a fill-ahead entropy reservoir."""

    def __init__(
        self,
        fmt: RawFormat = RawFormat(),
        *,
        sources: list[str] | None = None,
        rngoddess: bool = False,
        provider: Any = None,
        capacity: int = DEFAULT_CAPACITY,
        refill_size: int = DEFAULT_REFILL,
        block_frames: int = BLOCK_FRAMES,
        wait_timeout: float = 10.0,
    ) -> None:
        self.fmt = fmt
        self.source = provider if provider is not None else _ChunkSource(sources, rngoddess)
        self.block_bytes = block_frames * fmt.bytes_per_frame
        if self.block_bytes > capacity:
            raise ValueError("block larger than reservoir capacity")
        self.wait_timeout = wait_timeout
        self.reservoir = EntropyReservoir(self.source, capacity=capacity,
                                          refill_size=min(refill_size, capacity))
        self.raw_digest = hashlib.sha256()
        self.raw_bytes = 0

    def warm(self, minimum: int = DEFAULT_WARM, timeout: float = 30.0) -> bool:
        return self.reservoir.warm(min(minimum, self.reservoir.capacity), timeout=timeout)

    def blocks(self, total_bytes: int | None = None) -> Iterator[bytes]:
        """Yield mapped PCM blocks; unbounded when total_bytes is None."""
        remaining = total_bytes
        while remaining is None or remaining > 0:
            n = self.block_bytes if remaining is None else min(self.block_bytes, remaining)
            raw = self.reservoir.take_blocking(n, timeout=self.wait_timeout)
            self.raw_digest.update(raw)
            self.raw_bytes += len(raw)
            if remaining is not None:
                remaining -= n
            yield map_pcm(raw, self.fmt)

    def __iter__(self) -> Iterator[bytes]:
        return self.blocks()

    def status(self) -> dict[str, Any]:
        return self.reservoir.status()

    def close(self) -> None:
        self.reservoir.close()


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 16), b""):
            h.update(block)
    return h.hexdigest()


def render_wav(
    out: str | Path,
    seconds: float,
    fmt: RawFormat = RawFormat(),
    *,
    sources: list[str] | None = None,
    rngoddess: bool = False,
    provider: Any = None,
    warm: bool = False,
    **stream_kwargs: Any,
) -> dict[str, Any]:
    """Render raw entropy to a WAV plus a JSON provenance sidecar. Never plays."""
    if seconds <= 0:
        raise ValueError("seconds must be positive")
    out = Path(out)
    frames = int(round(seconds * fmt.rate))
    total = frames * fmt.bytes_per_frame
    stream = RawEntropyStream(fmt, sources=sources, rngoddess=rngoddess, provider=provider, **stream_kwargs)
    started = time.monotonic()
    try:
        if warm:
            stream.warm()
        with wave.open(str(out), "wb") as w:
            w.setnchannels(fmt.channels)
            w.setsampwidth(fmt.bits // 8)
            w.setframerate(fmt.rate)
            for block in stream.blocks(total):
                w.writeframesraw(block)
        elapsed = time.monotonic() - started
        status = stream.status()
    finally:
        stream.close()
    src = stream.source
    sidecar = {
        "schema": "mcfa-raw-entropy-audio/v1",
        "mode": "rngoddess" if getattr(src, "mixer", None) is not None else "single-source",
        "sources": list(getattr(src, "sources", [])),
        "format": {**asdict(fmt), "encoding": "u8" if fmt.bits == 8 else "s16le",
                   "mapping": "owie-u8" if fmt.bits == 8 else "s16le-pairs", "frames": frames},
        "seconds": frames / fmt.rate,
        "raw_bytes": stream.raw_bytes,
        "raw_sha256": stream.raw_digest.hexdigest(),
        "wav": str(out),
        "wav_sha256": _sha256_file(out),
        "underruns": status["underflows"],
        "underrun_missing_bytes": status["missing_bytes"],
        "provider_failures": status["provider_failures"],
        "producer_generated_bytes": status["generated_bytes"],
        "render_seconds": round(elapsed, 3),
        "fill_rate_bytes_per_s": round(status["generated_bytes"] / elapsed) if elapsed > 0 else None,
        "realtime_factor": round((frames / fmt.rate) / elapsed, 3) if elapsed > 0 else None,
        "last_chunk": status["last_chunk"],
        "rngoddess_manifests": list(getattr(src, "manifests", [])),
    }
    out.with_suffix(".json").write_text(json.dumps(sidecar, indent=2))
    return sidecar
