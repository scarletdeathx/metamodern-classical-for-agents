import hashlib
import json
import os
import struct
import tempfile
import threading
import time
import unittest
import wave

from mcfa.providers import EntropyChunk, EntropyProviderError, EntropyReservoir
from mcfa.raw_audio import RawEntropyStream, RawFormat, map_s16, map_u8, render_wav


class CounterSource:
    """Deterministic fake: bytes 0,1,2,... mod 256, optionally slow or failing."""

    def __init__(self, delay=0.0, fail_after=None):
        self.pos = 0
        self.delay = delay
        self.fail_after = fail_after
        self.reads = 0

    def read(self, n):
        self.reads += 1
        if self.fail_after is not None and self.reads > self.fail_after:
            raise EntropyProviderError("fake offline")
        if self.delay:
            time.sleep(self.delay)
        data = bytes((self.pos + i) % 256 for i in range(n))
        self.pos += n
        return EntropyChunk(data, "fake", "local", "fixture", "1", "t")


class MappingTests(unittest.TestCase):
    def test_u8_owie_mapping(self):
        self.assertEqual(map_u8(bytes([0, 128, 255]), 1.0), bytes([0, 128, 255]))
        # gain 0.5: b=0 -> -0.5 -> 64; b=128 -> 0 -> 128; b=255 -> ~0.496 -> 191
        self.assertEqual(map_u8(bytes([0, 128, 255]), 0.5), bytes([64, 128, 191]))
        self.assertEqual(map_u8(bytes([7]), 0.0), bytes([128]))

    def test_s16_mapping(self):
        raw = struct.pack("<hhh", -32768, 1000, 32767)
        self.assertEqual(map_s16(raw, 1.0), raw)
        self.assertEqual(struct.unpack("<hhh", map_s16(raw, 0.5)), (-16384, 500, 16384))
        with self.assertRaises(ValueError):
            map_s16(b"\x00", 0.5)

    def test_format_validation(self):
        for kw in ({"bits": 24}, {"rate": 10}, {"channels": 0}, {"gain": 2}):
            with self.subTest(kw=kw), self.assertRaises(ValueError):
                RawFormat(**kw)


class RenderTests(unittest.TestCase):
    def render(self, fmt, provider, seconds=0.25):
        d = tempfile.mkdtemp()
        path = os.path.join(d, "x.wav")
        meta = render_wav(path, seconds, fmt, provider=provider, capacity=65536, refill_size=8192, block_frames=1000)
        return path, meta

    def test_wav_header_and_sidecar(self):
        fmt = RawFormat(rate=8000, bits=16, channels=2, gain=1.0)
        path, meta = self.render(fmt, CounterSource())
        with wave.open(path) as w:
            self.assertEqual((w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()), (2, 2, 8000, 2000))
            frames = w.readframes(2000)
        expected = bytes(i % 256 for i in range(8000))
        self.assertEqual(frames, expected)  # gain 1.0 = raw bytes, no DSP
        self.assertEqual(meta["raw_bytes"], 8000)
        self.assertEqual(meta["raw_sha256"], hashlib.sha256(expected).hexdigest())
        with open(path, "rb") as f:
            self.assertEqual(meta["wav_sha256"], hashlib.sha256(f.read()).hexdigest())
        with open(path[:-4] + ".json") as f:
            side = json.load(f)
        self.assertEqual(side["format"]["encoding"], "s16le")
        self.assertEqual(side["underruns"], meta["underruns"])

    def test_u8_header(self):
        path, meta = self.render(RawFormat(rate=8000, bits=8), CounterSource())
        with wave.open(path) as w:
            self.assertEqual((w.getsampwidth(), w.getnframes()), (1, 2000))
        self.assertEqual(meta["format"]["mapping"], "owie-u8")

    def test_deterministic_with_fixed_source(self):
        fmt = RawFormat(rate=8000, bits=8)
        a = self.render(fmt, CounterSource())[1]["raw_sha256"]
        b = self.render(fmt, CounterSource())[1]["raw_sha256"]
        self.assertEqual(a, b)

    def test_no_fallback_on_failure(self):
        with self.assertRaises(EntropyProviderError):
            self.render(RawFormat(rate=8000, bits=16), CounterSource(fail_after=1), seconds=1.0)


class ReservoirStreamingTests(unittest.TestCase):
    def test_fast_source_never_underruns_after_warm(self):
        s = RawEntropyStream(RawFormat(rate=8000, bits=8), provider=CounterSource(),
                             capacity=32768, refill_size=4096, block_frames=800)
        try:
            self.assertTrue(s.warm(16384, timeout=2))
            for _ in s.blocks(8000):
                time.sleep(0.01)  # consumer slower than producer
            self.assertEqual(s.status()["underflows"], 0)
        finally:
            s.close()

    def test_slow_source_reports_underrun_but_never_invents_bytes(self):
        s = RawEntropyStream(RawFormat(rate=8000, bits=8, gain=1.0), provider=CounterSource(delay=0.02),
                             capacity=8192, refill_size=512, block_frames=2000)
        try:
            data = b"".join(s.blocks(4000))
            self.assertEqual(data, bytes(i % 256 for i in range(4000)))
            self.assertGreater(s.status()["underflows"], 0)
        finally:
            s.close()

    def test_take_blocking_times_out(self):
        class Never:
            def read(self, n):
                time.sleep(0.5)
                raise EntropyProviderError("never")
        r = EntropyReservoir(Never(), capacity=16, refill_size=16)
        try:
            with self.assertRaises(EntropyProviderError):
                r.take_blocking(8, timeout=0.1)
        finally:
            r.close()


if __name__ == "__main__":
    unittest.main()
