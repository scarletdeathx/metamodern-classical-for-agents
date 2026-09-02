"""Local ctypes adapter for Tsotchke's vendored ``quantum_rng`` v3 engine.

The adapter never contacts the public Tsotchke API. It loads a locally built
native library and is intended for MCFA's control plane, not the audio callback.
"""

from __future__ import annotations

import ctypes
import os
from pathlib import Path
import threading
from typing import Any

from .base import EntropyChunk, EntropyProviderError, EntropyProviderUnavailable


TSOTCHKE_SOURCE_REVISION = "1a77e77f803c63883349b658361c06401cd8ceb7"
MAX_READ_BYTES = 1 << 20


def find_tsotchke_library() -> Path:
    """Find an explicitly configured, packaged, or development library."""
    configured = os.environ.get("MCFA_TSOTCHKE_LIBRARY")
    candidates = []
    if configured:
        candidates.append(Path(configured).expanduser())
    package_root = Path(__file__).resolve().parents[1]
    candidates.append(package_root / "_native" / "libmcfa_tsotchke.dylib")
    repository_root = Path(__file__).resolve().parents[3]
    candidates.append(repository_root / ".dependency-work" / "builds" / "libmcfa_tsotchke.dylib")
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    checked = ", ".join(str(candidate) for candidate in candidates)
    raise EntropyProviderUnavailable(
        "Tsotchke local library is unavailable; run tools/build_tsotchke_local.sh "
        f"or set MCFA_TSOTCHKE_LIBRARY (checked: {checked})"
    )


def read_tsotchke_entropy(count: int) -> EntropyChunk:
    """Perform one bounded control-plane read from the local engine."""
    with TsotchkeLocalProvider(find_tsotchke_library()) as provider:
        return provider.read(count)


class TsotchkeLocalProvider:
    """Own one native QRNG context and expose bounded local byte reads."""

    def __init__(self, library_path: str | Path) -> None:
        self.library_path = Path(library_path).expanduser().resolve()
        if not self.library_path.is_file():
            raise EntropyProviderUnavailable(
                f"Tsotchke local library not found at {self.library_path}; "
                "run tools/build_tsotchke_local.sh or configure a packaged library"
            )
        try:
            self._library = ctypes.CDLL(str(self.library_path))
        except OSError as exc:
            raise EntropyProviderUnavailable(
                f"could not load Tsotchke local library at {self.library_path}: {exc}"
            ) from exc
        self._configure_abi()
        self._context = ctypes.c_void_p()
        self._lock = threading.Lock()
        error = self._library.qrng_v3_init(ctypes.byref(self._context))
        if error != 0 or not self._context.value:
            raise EntropyProviderError(f"Tsotchke engine initialization failed: {self._error(error)}")

    def _configure_abi(self) -> None:
        library = self._library
        library.qrng_v3_init.argtypes = [ctypes.POINTER(ctypes.c_void_p)]
        library.qrng_v3_init.restype = ctypes.c_int
        library.qrng_v3_free.argtypes = [ctypes.c_void_p]
        library.qrng_v3_free.restype = None
        library.qrng_v3_bytes.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint8), ctypes.c_size_t]
        library.qrng_v3_bytes.restype = ctypes.c_int
        library.qrng_v3_version.argtypes = []
        library.qrng_v3_version.restype = ctypes.c_char_p
        library.qrng_v3_error_string.argtypes = [ctypes.c_int]
        library.qrng_v3_error_string.restype = ctypes.c_char_p

    def _error(self, error: int) -> str:
        value = self._library.qrng_v3_error_string(int(error))
        return value.decode("utf-8", "replace") if value else f"error {error}"

    @property
    def engine_version(self) -> str:
        value = self._library.qrng_v3_version()
        return value.decode("utf-8", "replace") if value else "unknown"

    def read(self, count: int) -> EntropyChunk:
        if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= MAX_READ_BYTES:
            raise ValueError(f"count must be an integer between 1 and {MAX_READ_BYTES}")
        if not self._context.value:
            raise EntropyProviderError("Tsotchke local provider is closed")
        output = (ctypes.c_uint8 * count)()
        with self._lock:
            error = self._library.qrng_v3_bytes(self._context, output, count)
        if error != 0:
            raise EntropyProviderError(f"Tsotchke byte generation failed: {self._error(error)}")
        return EntropyChunk(
            data=bytes(output),
            provider="tsotchke-local",
            execution="local-state-vector-simulation",
            entropy_origin="conditioned-host-os-cpu",
            engine_version=self.engine_version,
            source_revision=TSOTCHKE_SOURCE_REVISION,
            physical_qpu=False,
        )

    def health(self) -> dict[str, Any]:
        return {
            "status": "ready" if self._context.value else "closed",
            "provider": "tsotchke-local",
            "execution": "local-state-vector-simulation",
            "entropy_origin": "conditioned-host-os-cpu",
            "engine_version": self.engine_version,
            "source_revision": TSOTCHKE_SOURCE_REVISION,
            "physical_qpu": False,
            "network_required": False,
            "library_path": str(self.library_path),
        }

    def close(self) -> None:
        with self._lock:
            if self._context.value:
                self._library.qrng_v3_free(self._context)
                self._context = ctypes.c_void_p()

    def __enter__(self) -> "TsotchkeLocalProvider":
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        self.close()
