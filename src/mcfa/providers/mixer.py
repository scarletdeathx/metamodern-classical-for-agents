"""RNGoddess: a cryptographic mixer over named entropy contributors.

Rubric mode #10 (V2_RNG_USER_RUBRIC.md, "RNGoddess (cryptographic mixer)") and
V2_RNG_DESIGN.md "Source composition": combine several named sources with a
documented cryptographic combiner and retain a per-epoch contribution manifest.
A failed contributor is never credited.

Combiner ``rngoddess-shake256-v1`` (versioned; part of the replay format):

    for each contributor i in configured order whose draw succeeded:
        block_i = u16be(len(name_i)) || name_i || u32be(len(data_i)) || data_i
    out = SHAKE256( "mcfa/v2/rngoddess/v1" || 0x00
                    || u16be(len(label)) || label
                    || u64be(epoch)
                    || u16be(k) || block_1 || ... || block_k ).read(n)

Each contributor supplies max(n, 32) bytes per epoch, so every input can carry
at least 256 bits into the extractor. An epoch is one call to ``read()``; the
counter starts at 1 per mixer instance and is recorded in the manifest.

Failure policy: contributors are required by default and any required failure
raises EntropyProviderError (no fallback to Python's random or to another
source). A contributor spelled with a trailing ``?`` is optional: when it fails
it is listed under ``failures`` and excluded from the hash input. At least one
contributor must succeed.
"""

from __future__ import annotations

import hashlib
import struct
from typing import Any, Callable, Iterable

from .base import EntropyChunk, EntropyProviderError

COMBINER = "rngoddess-shake256-v1"
DOMAIN_TAG = b"mcfa/v2/rngoddess/v1\x00"
MIN_CONTRIBUTION = 32
DEFAULT_SOURCES = ("eshkol-local:moonlab",)
MAX_READ_BYTES = 1 << 16
_BASE_SOURCES = {"system", "tsotchke-local", "eshkol-local"}

Reader = Callable[[int], EntropyChunk]


def parse_source(spec: str) -> tuple[str, str | None, bool]:
    """Split ``eshkol-local:moonlab?`` into (base, backend, required)."""
    if not isinstance(spec, str) or not spec.strip():
        raise ValueError("contributor source must be a non-empty string")
    text = spec.strip().lower()
    required = not text.endswith("?")
    text = text.rstrip("?")
    base, _, backend = text.partition(":")
    if base not in _BASE_SOURCES:
        raise ValueError(f"unknown contributor source {spec!r}; use one of {sorted(_BASE_SOURCES)}")
    if backend and base != "eshkol-local":
        raise ValueError(f"only eshkol-local takes a backend: {spec!r}")
    if base == "eshkol-local" and not backend:
        backend = None
    return base, backend or None, required


def normalize_sources(sources: Iterable[str] | None) -> list[str]:
    items = list(DEFAULT_SOURCES if sources is None else sources)
    if not items:
        raise ValueError("RNGoddess needs at least one contributor")
    out = []
    for spec in items:
        base, backend, required = parse_source(spec)
        name = base if backend is None else f"{base}:{backend}"
        out.append(name + ("" if required else "?"))
    if len({s.rstrip("?") for s in out}) != len(out):
        raise ValueError("duplicate RNGoddess contributor")
    return out


def default_reader(base: str, backend: str | None) -> Reader:
    if base == "system":
        from .system import SystemEntropyProvider

        return SystemEntropyProvider().read
    if base == "tsotchke-local":
        from .tsotchke import read_tsotchke_entropy

        return read_tsotchke_entropy
    from .eshkol import DEFAULT_BACKEND, read_eshkol_entropy

    chosen = backend or DEFAULT_BACKEND
    return lambda n: read_eshkol_entropy(n, backend=chosen)


def combine(label: bytes, epoch: int, blocks: list[tuple[str, bytes]], n: int) -> bytes:
    h = hashlib.shake_256()
    h.update(DOMAIN_TAG)
    h.update(struct.pack(">H", len(label)) + label)
    h.update(struct.pack(">Q", epoch))
    h.update(struct.pack(">H", len(blocks)))
    for name, data in blocks:
        raw = name.encode("utf-8")
        h.update(struct.pack(">H", len(raw)) + raw)
        h.update(struct.pack(">I", len(data)) + data)
    return h.digest(n)


class RNGoddessMixer:
    """Mix named contributors into one conditioned stream with a manifest."""

    def __init__(
        self,
        sources: Iterable[str] | None = None,
        *,
        label: str = "mcfa/v2/rngoddess",
        readers: dict[str, Reader] | None = None,
    ) -> None:
        self.sources = normalize_sources(sources)
        self.label = label.encode("utf-8")
        self.epoch = 0
        self._readers = dict(readers or {})
        self.last_manifest: dict[str, Any] | None = None

    def _reader(self, name: str) -> Reader:
        if name not in self._readers:
            base, backend, _ = parse_source(name)
            self._readers[name] = default_reader(base, backend)
        return self._readers[name]

    def read(self, count: int) -> EntropyChunk:
        if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= MAX_READ_BYTES:
            raise ValueError(f"count must be an integer between 1 and {MAX_READ_BYTES}")
        self.epoch += 1
        want = max(count, MIN_CONTRIBUTION)
        blocks: list[tuple[str, bytes]] = []
        contributors: list[dict[str, Any]] = []
        failures: list[dict[str, Any]] = []
        for spec in self.sources:
            name = spec.rstrip("?")
            required = not spec.endswith("?")
            try:
                chunk = self._reader(name)(want)
                if len(chunk.data) != want:
                    raise EntropyProviderError(f"returned {len(chunk.data)} bytes, expected {want}")
            except Exception as exc:  # noqa: BLE001 - recorded, then re-raised if required
                failures.append({"source": name, "required": required, "error": str(exc)})
                if required:
                    raise EntropyProviderError(
                        f"RNGoddess required contributor {name} failed in epoch {self.epoch}: {exc}"
                    ) from exc
                continue
            blocks.append((name, chunk.data))
            contributors.append({
                "source": name,
                "provider": chunk.provider,
                "execution": chunk.execution,
                "entropy_origin": chunk.entropy_origin,
                "physical_qpu": chunk.physical_qpu,
                "bytes": len(chunk.data),
                "sha256": chunk.sha256,
            })
        if not blocks:
            raise EntropyProviderError(f"RNGoddess epoch {self.epoch}: no contributor succeeded")
        out = combine(self.label, self.epoch, blocks, count)
        self.last_manifest = {
            "schema": "mcfa-rngoddess-manifest/v1",
            "combiner": COMBINER,
            "label": self.label.decode("utf-8"),
            "epoch": self.epoch,
            "contributors": contributors,
            "failures": failures,
            "output_bytes": count,
            "output_sha256": hashlib.sha256(out).hexdigest(),
        }
        return EntropyChunk(
            data=out,
            provider="rngoddess",
            execution="local-mixer",
            entropy_origin="mixed:" + "+".join(c["source"] for c in contributors),
            engine_version=COMBINER,
            source_revision="mixer-v1",
            physical_qpu=any(c["physical_qpu"] for c in contributors),
        )

    def provenance(self) -> dict[str, Any]:
        """Last epoch's manifest (contributors, byte counts, hashes, failures)."""
        if self.last_manifest is None:
            raise EntropyProviderError("RNGoddess has not produced an epoch yet")
        return dict(self.last_manifest)

    def close(self) -> None:
        return None
