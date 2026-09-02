import unittest

from mcfa.rng import build_stream, derive_seed


class RandomStreamTests(unittest.TestCase):
    def test_derived_seeds_are_stable_and_domain_separated(self):
        self.assertEqual(derive_seed(1, "decision"), derive_seed(1, "decision"))
        self.assertNotEqual(derive_seed(1, "decision"), derive_seed(1, "sound"))
        self.assertNotEqual(derive_seed(1, "sound"), derive_seed(2, "sound"))

    def test_each_local_algorithm_replays_from_its_seed(self):
        for algorithm in ("pcg64dxsm", "philox", "chacha20", "lfsr15", "legacy-mt19937"):
            with self.subTest(algorithm=algorithm):
                first = build_stream(algorithm, 0x12345678)
                second = build_stream(algorithm, 0x12345678)
                self.assertEqual(list(first.random(64)), list(second.random(64)))

    def test_algorithms_do_not_collapse_to_the_same_stream(self):
        streams = {
            algorithm: tuple(build_stream(algorithm, 99).random(8))
            for algorithm in ("pcg64dxsm", "philox", "chacha20", "lfsr15", "legacy-mt19937")
        }
        self.assertEqual(len(set(streams.values())), len(streams))


if __name__ == "__main__":
    unittest.main()
