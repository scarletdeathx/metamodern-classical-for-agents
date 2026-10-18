import hashlib
import unittest

from mcfa.model import RNGDomain, ValidationError
from mcfa.providers import EntropyChunk, EntropyProviderError
from mcfa.providers.mixer import COMBINER, RNGoddessMixer, combine, normalize_sources
from mcfa.rng import FRIENDLY_SOURCE_NAMES


def fixed(byte: int, provider: str = "fixture"):
    def read(n):
        return EntropyChunk(bytes([byte]) * n, provider, "local", "fixture", "1", "t")
    return read


def broken(n):
    raise EntropyProviderError("offline")


class RNGoddessMixerTests(unittest.TestCase):
    def mixer(self, sources, readers):
        return RNGoddessMixer(sources, label="test", readers=readers)

    def test_default_contributor_is_moonlab(self):
        self.assertEqual(RNGoddessMixer().sources, ["eshkol-local:moonlab"])
        self.assertEqual(FRIENDLY_SOURCE_NAMES["mixed"], "RNGoddess")

    def test_deterministic_for_fixed_inputs(self):
        readers = {"system": fixed(1), "eshkol-local:moonlab": fixed(2)}
        a = self.mixer(["eshkol-local:moonlab", "system"], readers).read(16).data
        b = self.mixer(["eshkol-local:moonlab", "system"], readers).read(16).data
        self.assertEqual(a, b)
        self.assertEqual(a, combine(b"test", 1, [("eshkol-local:moonlab", b"\x02" * 32), ("system", b"\x01" * 32)], 16))

    def test_epoch_order_and_label_change_output(self):
        readers = {"system": fixed(1), "eshkol-local:moonlab": fixed(2)}
        m = self.mixer(["eshkol-local:moonlab", "system"], readers)
        first, second = m.read(16).data, m.read(16).data
        self.assertNotEqual(first, second)
        swapped = self.mixer(["system", "eshkol-local:moonlab"], readers).read(16).data
        self.assertNotEqual(first, swapped)
        other = RNGoddessMixer(["eshkol-local:moonlab", "system"], label="x", readers=readers).read(16).data
        self.assertNotEqual(first, other)

    def test_manifest_records_contributors(self):
        m = self.mixer(["eshkol-local:moonlab", "system"], {"system": fixed(1, "os"), "eshkol-local:moonlab": fixed(2, "eshkol-moonlab")})
        out = m.read(8)
        man = m.provenance()
        self.assertEqual(man["combiner"], COMBINER)
        self.assertEqual(man["epoch"], 1)
        self.assertEqual([c["source"] for c in man["contributors"]], ["eshkol-local:moonlab", "system"])
        self.assertEqual(man["contributors"][0]["provider"], "eshkol-moonlab")
        self.assertEqual(man["contributors"][0]["bytes"], 32)
        self.assertEqual(man["contributors"][0]["sha256"], hashlib.sha256(b"\x02" * 32).hexdigest())
        self.assertEqual(man["failures"], [])
        self.assertEqual(man["output_sha256"], hashlib.sha256(out.data).hexdigest())
        self.assertEqual(out.provider, "rngoddess")

    def test_required_failure_raises(self):
        m = self.mixer(["eshkol-local:moonlab", "system"], {"system": fixed(1), "eshkol-local:moonlab": broken})
        with self.assertRaisesRegex(EntropyProviderError, "required contributor eshkol-local:moonlab"):
            m.read(16)

    def test_optional_failure_is_not_credited(self):
        m = self.mixer(["eshkol-local:moonlab", "system?"], {"system": broken, "eshkol-local:moonlab": fixed(2)})
        out = m.read(16)
        man = m.provenance()
        self.assertEqual([c["source"] for c in man["contributors"]], ["eshkol-local:moonlab"])
        self.assertEqual(man["failures"][0]["source"], "system")
        self.assertFalse(man["failures"][0]["required"])
        self.assertEqual(out.data, combine(b"test", 1, [("eshkol-local:moonlab", b"\x02" * 32)], 16))

    def test_all_optional_failing_raises(self):
        m = self.mixer(["system?"], {"system": broken})
        with self.assertRaises(EntropyProviderError):
            m.read(16)

    def test_source_validation(self):
        self.assertEqual(normalize_sources(["Eshkol-Local:Moonlab", "system?"]), ["eshkol-local:moonlab", "system?"])
        for bad in ([], ["nope"], ["system:x"], ["system", "system?"]):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                normalize_sources(bad)


class MixedDomainModelTests(unittest.TestCase):
    def test_mixed_mode_validates(self):
        d = RNGDomain()
        d.update({"mode": "mixed", "seed": 5, "sources": ["eshkol-local:moonlab"]})
        self.assertEqual(d.source, "mixed")
        self.assertEqual(d.public()["source_label"], "RNGoddess")
        with self.assertRaises(ValidationError):
            RNGDomain().update({"mode": "mixed", "sources": ["system"]})  # unresolved seed
        with self.assertRaises(ValidationError):
            RNGDomain().update({"mode": "seeded", "seed": 1, "sources": ["system"]})

    def test_fresh_eshkol_backend(self):
        d = RNGDomain()
        d.update({"mode": "fresh", "source": "eshkol-local:moonlab", "seed": 1})
        self.assertEqual(d.public()["source_label"], None)
        with self.assertRaises(ValidationError):
            RNGDomain().update({"mode": "fresh", "source": "eshkol-local:", "seed": 1})


if __name__ == "__main__":
    unittest.main()
