import unittest

from mcfa.providers import EntropyChunk, EntropyReservoir


class CountingProvider:
    def __init__(self) -> None:
        self.offset = 0

    def read(self, count: int) -> EntropyChunk:
        data = bytes((self.offset + index) % 256 for index in range(count))
        self.offset += count
        return EntropyChunk(data, "fixture", "test", "counter", "1", "test")


class FailingProvider:
    def read(self, count: int) -> EntropyChunk:
        raise RuntimeError("deliberate provider failure")


class ShortProvider:
    def read(self, count: int) -> EntropyChunk:
        return EntropyChunk(b"x", "fixture", "test", "short", "1", "test")


class EntropyReservoirTests(unittest.TestCase):
    def test_control_plane_refill_and_nonblocking_take(self):
        reservoir = EntropyReservoir(CountingProvider(), capacity=16, refill_size=8, low_watermark=4)
        self.assertTrue(reservoir.refill_once())
        self.assertTrue(reservoir.refill_once())
        self.assertEqual(reservoir.take(10), bytes(range(10)))
        self.assertIsNone(reservoir.take(7))
        status = reservoir.status()
        self.assertEqual(status["available_bytes"], 6)
        self.assertEqual(status["delivered_bytes"], 10)
        self.assertEqual(status["underflows"], 1)
        self.assertEqual(status["missing_bytes"], 1)
        reservoir.close()

    def test_background_warm_fills_to_requested_level(self):
        reservoir = EntropyReservoir(CountingProvider(), capacity=32, refill_size=8, low_watermark=16)
        try:
            self.assertTrue(reservoir.warm(24, timeout=1.0))
            self.assertGreaterEqual(reservoir.status()["available_bytes"], 24)
        finally:
            reservoir.close()

    def test_provider_failure_is_reported_without_raising_to_consumer(self):
        reservoir = EntropyReservoir(FailingProvider(), capacity=16, refill_size=8)
        self.assertFalse(reservoir.refill_once())
        self.assertIsNone(reservoir.take(4))
        status = reservoir.status()
        self.assertEqual(status["provider_failures"], 1)
        self.assertIn("deliberate provider failure", status["last_error"])
        reservoir.close()

    def test_short_provider_result_is_rejected(self):
        reservoir = EntropyReservoir(ShortProvider(), capacity=16, refill_size=8)
        self.assertFalse(reservoir.refill_once())
        self.assertEqual(reservoir.status()["available_bytes"], 0)
        self.assertIn("expected 8", reservoir.status()["last_error"])
        reservoir.close()

    def test_bounds_are_explicit(self):
        with self.assertRaises(ValueError):
            EntropyReservoir(CountingProvider(), capacity=0)
        reservoir = EntropyReservoir(CountingProvider(), capacity=8, refill_size=4)
        with self.assertRaises(ValueError):
            reservoir.take(9)
        reservoir.close()


if __name__ == "__main__":
    unittest.main()
