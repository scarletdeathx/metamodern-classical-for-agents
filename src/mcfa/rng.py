"""Versioned random streams for MCFA's lane-local decision and sound domains.

This module contains deterministic generators only.  Operating-system and remote
entropy are resolved or buffered by the engine's control plane before a stream is
constructed; the audio renderer never performs entropy I/O.
"""

from __future__ import annotations

import hashlib
import math
import random
from typing import Any

try:
    import numpy as _np
except ImportError:  # pragma: no cover - the legacy path remains dependency-free.
    _np = None


ALGORITHMS = {"pcg64dxsm", "philox", "chacha20", "lfsr15", "legacy-mt19937"}
FRIENDLY_ALGORITHM_NAMES = {
    "pcg64dxsm": "Queue Chiral",
    "philox": "Orthogonal Lysis",
    "chacha20": "Cliodynamic Threnody",
    "lfsr15": "Circuit Bender",
    "legacy-mt19937": "Legacy compatibility",
}
FRIENDLY_SOURCE_NAMES = {
    "system": "Soft Reset",
    "tsotchke-local": "Decoherence Engine",
}
DEFAULT_ROOT_SEED = 0x4D4346415F56325F524E475F524F4F54


def derive_seed(lane_id: int, domain: str, *, root_seed: int = DEFAULT_ROOT_SEED) -> int:
    """Derive a stable 128-bit lane/domain seed without consuming another stream."""
    label = f"mcfa/v2/lane/{int(lane_id):02d}/{domain}".encode("ascii")
    root = int(root_seed).to_bytes(16, "big", signed=False)
    return int.from_bytes(hashlib.blake2b(label, key=root, digest_size=16).digest(), "big")


class RandomStream:
    """Small common surface used by scalar and NumPy render paths."""

    def random(self, size: int | None = None) -> Any:
        raise NotImplementedError


class PythonRandomStream(RandomStream):
    def __init__(self, seed: int) -> None:
        self._rng = random.Random(int(seed))

    def random(self, size: int | None = None) -> Any:
        if size is None:
            return self._rng.random()
        values = [self._rng.random() for _ in range(int(size))]
        return _np.asarray(values, dtype=_np.float64) if _np is not None else values


class NumPyRandomStream(RandomStream):
    def __init__(self, algorithm: str, seed: int) -> None:
        if _np is None:
            raise RuntimeError(f"{algorithm} requires NumPy")
        bit_generator = _np.random.PCG64DXSM(seed) if algorithm == "pcg64dxsm" else _np.random.Philox(seed)
        self._rng = _np.random.Generator(bit_generator)

    def random(self, size: int | None = None) -> Any:
        return self._rng.random(size)


def _rotate_left(value: int, shift: int) -> int:
    return ((value << shift) & 0xFFFFFFFF) | (value >> (32 - shift))


def _quarter_round(state: list[int], a: int, b: int, c: int, d: int) -> None:
    state[a] = (state[a] + state[b]) & 0xFFFFFFFF
    state[d] = _rotate_left(state[d] ^ state[a], 16)
    state[c] = (state[c] + state[d]) & 0xFFFFFFFF
    state[b] = _rotate_left(state[b] ^ state[c], 12)
    state[a] = (state[a] + state[b]) & 0xFFFFFFFF
    state[d] = _rotate_left(state[d] ^ state[a], 8)
    state[c] = (state[c] + state[d]) & 0xFFFFFFFF
    state[b] = _rotate_left(state[b] ^ state[c], 7)


class ChaCha20Stream(RandomStream):
    """Deterministic IETF-style ChaCha20 core with an MCFA-derived key/nonce.

    This is an internal stream generator, not a general cryptographic API.  It
    intentionally exposes no encryption operation and is covered by fixed-vector
    reproducibility tests in MCFA.
    """

    def __init__(self, seed: int) -> None:
        material = hashlib.sha512(int(seed).to_bytes(16, "big") + b"mcfa/v2/chacha20").digest()
        self._key_words = [int.from_bytes(material[i : i + 4], "little") for i in range(0, 32, 4)]
        self._nonce_words = [int.from_bytes(material[i : i + 4], "little") for i in range(32, 44, 4)]
        self._counter = 0
        self._buffer = bytearray()

    def _block(self) -> bytes:
        constants = [0x61707865, 0x3320646E, 0x79622D32, 0x6B206574]
        initial = constants + self._key_words + [self._counter & 0xFFFFFFFF] + self._nonce_words
        working = initial.copy()
        for _ in range(10):
            _quarter_round(working, 0, 4, 8, 12)
            _quarter_round(working, 1, 5, 9, 13)
            _quarter_round(working, 2, 6, 10, 14)
            _quarter_round(working, 3, 7, 11, 15)
            _quarter_round(working, 0, 5, 10, 15)
            _quarter_round(working, 1, 6, 11, 12)
            _quarter_round(working, 2, 7, 8, 13)
            _quarter_round(working, 3, 4, 9, 14)
        self._counter = (self._counter + 1) & 0xFFFFFFFF
        return b"".join(((working[i] + initial[i]) & 0xFFFFFFFF).to_bytes(4, "little") for i in range(16))

    def _blocks_numpy(self, count: int) -> bytes:
        if _np is None:
            return b"".join(self._block() for _ in range(count))
        constants = _np.asarray([0x61707865, 0x3320646E, 0x79622D32, 0x6B206574], dtype=_np.uint32)
        initial = _np.empty((count, 16), dtype=_np.uint32)
        initial[:, 0:4] = constants
        initial[:, 4:12] = _np.asarray(self._key_words, dtype=_np.uint32)
        counters = (_np.arange(count, dtype=_np.uint64) + self._counter) & 0xFFFFFFFF
        initial[:, 12] = counters.astype(_np.uint32)
        initial[:, 13:16] = _np.asarray(self._nonce_words, dtype=_np.uint32)
        working = initial.copy()

        def quarter(a: int, b: int, c: int, d: int) -> None:
            working[:, a] += working[:, b]
            working[:, d] ^= working[:, a]
            working[:, d] = (working[:, d] << _np.uint32(16)) | (working[:, d] >> _np.uint32(16))
            working[:, c] += working[:, d]
            working[:, b] ^= working[:, c]
            working[:, b] = (working[:, b] << _np.uint32(12)) | (working[:, b] >> _np.uint32(20))
            working[:, a] += working[:, b]
            working[:, d] ^= working[:, a]
            working[:, d] = (working[:, d] << _np.uint32(8)) | (working[:, d] >> _np.uint32(24))
            working[:, c] += working[:, d]
            working[:, b] ^= working[:, c]
            working[:, b] = (working[:, b] << _np.uint32(7)) | (working[:, b] >> _np.uint32(25))

        for _ in range(10):
            quarter(0, 4, 8, 12)
            quarter(1, 5, 9, 13)
            quarter(2, 6, 10, 14)
            quarter(3, 7, 11, 15)
            quarter(0, 5, 10, 15)
            quarter(1, 6, 11, 12)
            quarter(2, 7, 8, 13)
            quarter(3, 4, 9, 14)
        output = working + initial
        self._counter = (self._counter + count) & 0xFFFFFFFF
        return output.astype("<u4", copy=False).tobytes()

    def _take(self, count: int) -> bytes:
        while len(self._buffer) < count:
            blocks = math.ceil((count - len(self._buffer)) / 64)
            # NumPy ChaCha has a fixed vectorization cost.  Refill a modest
            # reservoir on the control-free local stream so audio blocks do not
            # pay that setup cost for every active voice.
            if _np is not None:
                blocks = max(blocks, 1024)
            self._buffer.extend(self._blocks_numpy(blocks) if blocks > 1 else self._block())
        result = bytes(self._buffer[:count])
        del self._buffer[:count]
        return result

    def random(self, size: int | None = None) -> Any:
        count = 1 if size is None else int(size)
        raw = self._take(count * 8)
        # Use the high 53 bits, matching the precision of ordinary Python floats.
        values = [((int.from_bytes(raw[i : i + 8], "little") >> 11) / 2**53) for i in range(0, len(raw), 8)]
        if size is None:
            return values[0]
        return _np.asarray(values, dtype=_np.float64) if _np is not None else values


class LFSR15Stream(RandomStream):
    """A deliberately cyclic 15-bit stream for tracker-like machine noise."""

    def __init__(self, seed: int) -> None:
        self._state = int(seed) & 0x7FFF or 1
        self._position = 0
        values = [self._word() for _ in range(32767)]
        self._cycle = _np.asarray(values, dtype=_np.float64) if _np is not None else values

    def _word(self) -> float:
        value = 0
        for _ in range(15):
            # NES-style 15-bit mode: XOR bits 0 and 1, shift right, and feed bit 14.
            feedback = (self._state ^ (self._state >> 1)) & 1
            self._state = (self._state >> 1) | (feedback << 14)
            value = (value << 1) | (self._state & 1)
        return value / 32768.0

    def random(self, size: int | None = None) -> Any:
        if size is None:
            value = float(self._cycle[self._position])
            self._position = (self._position + 1) % len(self._cycle)
            return value
        count = int(size)
        if _np is not None:
            indices = (_np.arange(count) + self._position) % len(self._cycle)
            self._position = (self._position + count) % len(self._cycle)
            return self._cycle[indices]
        values = [self._cycle[(self._position + index) % len(self._cycle)] for index in range(count)]
        self._position = (self._position + count) % len(self._cycle)
        return values


class OffStream(RandomStream):
    def random(self, size: int | None = None) -> Any:
        if size is None:
            return 0.5
        if _np is not None:
            return _np.full(int(size), 0.5, dtype=_np.float64)
        return [0.5] * int(size)


def build_stream(algorithm: str, seed: int, *, off: bool = False) -> RandomStream:
    if off:
        return OffStream()
    if algorithm == "legacy-mt19937":
        return PythonRandomStream(seed)
    if algorithm in {"pcg64dxsm", "philox"}:
        return NumPyRandomStream(algorithm, seed)
    if algorithm == "chacha20":
        return ChaCha20Stream(seed)
    if algorithm == "lfsr15":
        return LFSR15Stream(seed)
    raise ValueError(f"unknown RNG algorithm {algorithm!r}")
