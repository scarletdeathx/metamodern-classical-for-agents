"""Small provider-neutral values shared by local entropy adapters."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from typing import Any


class EntropyProviderError(RuntimeError):
    """An entropy provider was found but could not fulfill a request."""


class EntropyProviderUnavailable(EntropyProviderError):
    """An optional entropy provider is not installed or configured."""


@dataclass(frozen=True)
class EntropyChunk:
    """A bounded block of entropy plus enough provenance to audit its origin."""

    data: bytes
    provider: str
    execution: str
    entropy_origin: str
    engine_version: str
    source_revision: str
    physical_qpu: bool = False

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.data).hexdigest()

    def provenance(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "execution": self.execution,
            "entropy_origin": self.entropy_origin,
            "engine_version": self.engine_version,
            "source_revision": self.source_revision,
            "physical_qpu": self.physical_qpu,
            "bytes": len(self.data),
            "sha256": self.sha256,
        }
