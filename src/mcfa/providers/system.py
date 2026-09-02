"""Operating-system entropy provider for control-plane and reservoir use."""

from __future__ import annotations

import os
import platform
from typing import Any

from .base import EntropyChunk


MAX_READ_BYTES = 1 << 20


class SystemEntropyProvider:
    """Read bounded chunks from the host CSPRNG outside the audio callback."""

    def read(self, count: int) -> EntropyChunk:
        if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= MAX_READ_BYTES:
            raise ValueError(f"count must be an integer between 1 and {MAX_READ_BYTES}")
        return EntropyChunk(
            data=os.urandom(count),
            provider="system",
            execution="local-os",
            entropy_origin="host-os-csprng",
            engine_version=platform.release(),
            source_revision="host-runtime",
            physical_qpu=False,
        )

    def health(self) -> dict[str, Any]:
        return {
            "status": "ready",
            "provider": "system",
            "execution": "local-os",
            "entropy_origin": "host-os-csprng",
            "physical_qpu": False,
            "network_required": False,
        }

    def close(self) -> None:
        return None
