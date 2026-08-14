import sys
import types
import unittest
from unittest.mock import patch

from mcfa.daemon import SoundDeviceBackend
from mcfa.synth import SynthEngine


class FakeRawOutputStream:
    instances = []

    def __init__(self, **options):
        self.options = options
        self.started = False
        self.stopped = False
        self.closed = False
        self.writes = []
        self.instances.append(self)

    def start(self):
        self.started = True

    def write(self, data):
        self.writes.append(data)
        return False

    def stop(self):
        self.stopped = True

    def close(self):
        self.closed = True


class CoreAudioAdapterTests(unittest.TestCase):
    def test_raw_stream_accepts_dependency_free_float_buffers(self):
        fake_sounddevice = types.SimpleNamespace(RawOutputStream=FakeRawOutputStream)
        engine = SynthEngine(
            bpm=120,
            sample_rate=8000,
            backend_name="sounddevice",
            duration=0.02,
            deadline_fade=0.005,
        )
        with patch.dict(sys.modules, {"sounddevice": fake_sounddevice}):
            backend = SoundDeviceBackend(engine, block_size=64)
            backend.start()
            backend.thread.join(timeout=2.0)
            backend.close()
        stream = FakeRawOutputStream.instances[-1]
        self.assertTrue(stream.started and stream.stopped and stream.closed)
        self.assertEqual(stream.options["latency"], "high")
        self.assertEqual(stream.options["blocksize"], 64)
        self.assertTrue(stream.writes)
        self.assertTrue(all(len(block) == 64 * 2 * 4 for block in stream.writes))
        self.assertIsNone(backend.error)
        self.assertFalse(engine.running)


if __name__ == "__main__":
    unittest.main()
