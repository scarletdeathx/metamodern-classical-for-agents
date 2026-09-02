import hashlib
from pathlib import Path
import unittest

from mcfa.providers import EntropyChunk, EntropyProviderError, EntropyProviderUnavailable, SystemEntropyProvider
from mcfa.providers.tsotchke import MAX_READ_BYTES, TsotchkeLocalProvider


class EntropyChunkTests(unittest.TestCase):
    def test_provenance_hashes_exact_bytes(self):
        chunk = EntropyChunk(
            data=b"mcfa",
            provider="test",
            execution="local",
            entropy_origin="fixture",
            engine_version="1",
            source_revision="abc",
        )
        provenance = chunk.provenance()
        self.assertEqual(provenance["bytes"], 4)
        self.assertEqual(provenance["sha256"], hashlib.sha256(b"mcfa").hexdigest())
        self.assertFalse(provenance["physical_qpu"])


class TsotchkeLocalProviderValidationTests(unittest.TestCase):
    def test_missing_library_is_an_optional_provider_error(self):
        with self.assertRaises(EntropyProviderUnavailable):
            TsotchkeLocalProvider(Path("/definitely/not/an/mcfa/library.dylib"))

    def test_read_bounds_are_explicit(self):
        provider = object.__new__(TsotchkeLocalProvider)
        provider._context = type("Context", (), {"value": 1})()
        for count in (0, -1, MAX_READ_BYTES + 1, True, 1.5):
            with self.subTest(count=count), self.assertRaises(ValueError):
                provider.read(count)

    def test_closed_provider_fails_before_native_call(self):
        provider = object.__new__(TsotchkeLocalProvider)
        provider._context = type("Context", (), {"value": None})()
        with self.assertRaisesRegex(EntropyProviderError, "closed"):
            provider.read(16)


class SystemEntropyProviderTests(unittest.TestCase):
    def test_reads_exact_bounded_chunk_with_honest_provenance(self):
        chunk = SystemEntropyProvider().read(16)
        self.assertEqual(len(chunk.data), 16)
        self.assertEqual(chunk.provider, "system")
        self.assertEqual(chunk.entropy_origin, "host-os-csprng")
        self.assertFalse(chunk.physical_qpu)

    def test_read_bounds_are_explicit(self):
        provider = SystemEntropyProvider()
        for count in (0, -1, (1 << 20) + 1, True, 1.5):
            with self.subTest(count=count), self.assertRaises(ValueError):
                provider.read(count)


if __name__ == "__main__":
    unittest.main()
