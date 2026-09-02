import unittest
import time
from unittest import mock

from mcfa.model import parse_pattern
from mcfa import synth as synth_module
from mcfa.synth import SynthEngine


def compact(text):
    return [step.public() for step in parse_pattern(text)]


class SynthEngineTests(unittest.TestCase):
    def make_engine(self, **kwargs):
        return SynthEngine(bpm=kwargs.pop("bpm", 120), sample_rate=8000, backend_name="test", **kwargs)

    def test_engine_run_has_system_random_entropy_stamp(self):
        with mock.patch.object(synth_module._SYSTEM_RANDOM, "getrandbits", return_value=0x1234):
            engine = self.make_engine()
        expected = "00000000000000000000000000001234"
        self.assertEqual(engine.status()["entropy_stamp"], expected)
        self.assertEqual(engine.compact_status()["entropy_stamp"], expected)

    def test_pattern_renders_audio_and_exposes_runtime_state(self):
        engine = self.make_engine()
        engine.schedule(
            "set",
            {
                "channel": 1,
                "patch": {
                    "name": "pulse",
                    "pattern": compact("C3 . E3 ."),
                    "step_beats": 0.25,
                    "volume": 0.4,
                    "pan": -0.5,
                    "synth": {
                        "waveform": "triangle",
                        "filter": {"type": "lowpass", "cutoff": 1400, "resonance": 0.2},
                        "envelope": {"attack": 0.001, "release": 0.03},
                        "effects": {"drive": 0.1, "delay_mix": 0.1},
                    },
                },
            },
            fade=0,
        )
        audio = engine.render(4000)
        self.assertEqual(len(audio), 8000)
        self.assertGreater(max(abs(value) for value in audio), 0.01)
        status = engine.status()
        channel = status["channels"][0]
        self.assertEqual(channel["name"], "pulse")
        self.assertEqual(channel["loop_steps"], 4)
        self.assertEqual(channel["synth"]["waveform"], "triangle")
        self.assertGreater(channel["runtime"]["level"]["peak"], 0)

    def test_quantized_change_applies_without_resetting_transport(self):
        engine = self.make_engine(bpm=60)
        engine.schedule("set", {"channel": 1, "patch": {"pattern": compact("C3 .")}}, fade=0)
        engine.render(2000)
        before = engine.status()
        scheduled = engine.schedule(
            "set",
            {"channel": 1, "patch": {"volume": 0.2, "synth": {"filter": {"cutoff": 700}}}},
            at="next-beat",
            fade=0.1,
        )
        self.assertEqual(scheduled["at_beat"], 1.0)
        engine.render(5999)
        self.assertEqual(engine.status()["channels"][0]["volume"], 0.65)
        engine.render(2)
        after = engine.status()
        self.assertEqual(after["channels"][0]["volume"], 0.2)
        self.assertGreater(after["transport"]["frame"], before["transport"]["frame"])
        self.assertTrue(after["running"])

    def test_atomic_batch_populates_all_ten_channels(self):
        engine = self.make_engine(bpm=200)
        items = []
        for channel in range(1, 11):
            items.append(
                {
                    "channel": channel,
                    "patch": {
                        "pattern": compact(f"C{2 + channel % 3} ."),
                        "step_beats": 0.5,
                        "clock": "free",
                        "bpm": 47 + channel * 17,
                        "volume": 0.08,
                        "pan": -1 + (channel - 1) * 2 / 9,
                    },
                }
            )
        engine.schedule("batch", {"items": items}, fade=0)
        engine.render(512)
        state = engine.status()
        self.assertEqual(sum(bool(channel["pattern"]) for channel in state["channels"]), 10)
        self.assertTrue(state["running"])
        self.assertEqual(state["transport"]["frame"], 512)
        self.assertEqual(len({channel["bpm"] for channel in state["channels"]}), 10)

    def test_deadline_owns_fade_and_stop(self):
        engine = self.make_engine(duration=0.1, deadline_fade=0.025)
        engine.schedule("set", {"channel": 1, "patch": {"pattern": compact("C3")}}, fade=0)
        engine.render(801)
        state = engine.status()
        self.assertFalse(state["running"])
        self.assertEqual(state["stop_reason"], "deadline")
        self.assertEqual(state["master_volume"], 0.0)

    def test_panic_is_immediate_and_clears_work(self):
        engine = self.make_engine()
        engine.schedule("set", {"channel": 1, "patch": {"pattern": compact("C3")}}, at="next-bar")
        engine.panic()
        state = engine.status()
        self.assertFalse(state["running"])
        self.assertEqual(state["stop_reason"], "panic")
        self.assertEqual(state["scheduled"], [])

    def test_free_lanes_keep_independent_clocks_and_ignore_master_tempo(self):
        engine = self.make_engine(bpm=120)
        engine.schedule(
            "batch",
            {
                "items": [
                    {"channel": 1, "patch": {"pattern": compact("C3 . C3"), "clock": "free", "bpm": 60, "step_beats": 0.25}},
                    {"channel": 2, "patch": {"pattern": compact("C4 . C4"), "clock": "free", "bpm": 180, "step_beats": 0.25}},
                    {"channel": 3, "patch": {"pattern": compact("C5 . C5"), "clock": "sync", "step_beats": 0.25}},
                ]
            },
            fade=0,
        )
        engine.render(8000)
        first = engine.compact_status()
        self.assertAlmostEqual(first["channels"][0]["local_beat"], 1.0, places=2)
        self.assertAlmostEqual(first["channels"][1]["local_beat"], 3.0, places=2)
        self.assertAlmostEqual(first["channels"][2]["local_beat"], 2.0, places=2)
        engine.schedule("tempo", {"bpm": 240}, fade=0)
        engine.render(8000)
        second = engine.compact_status()
        self.assertAlmostEqual(second["channels"][0]["local_beat"], 2.0, places=2)
        self.assertAlmostEqual(second["channels"][1]["local_beat"], 6.0, places=2)
        self.assertAlmostEqual(second["channels"][2]["local_beat"], 6.0, places=2)

    def test_kill_rewrite_restart_is_isolated_and_auditable(self):
        engine = self.make_engine()
        engine.schedule("set", {"channel": 1, "patch": {"name": "victim", "pattern": compact("C3")}}, fade=0)
        engine.schedule("set", {"channel": 2, "patch": {"name": "survivor", "pattern": compact("C4 .")}}, fade=0)
        engine.render(1000)
        survivor_frame = engine.channels[1].last_trigger_frame
        engine.schedule("kill", {"channel": 1}, fade=0)
        killed = engine.status()["channels"][0]
        self.assertFalse(killed["active"])
        self.assertEqual(killed["runtime"]["active_voices"], 0)
        engine.schedule("set", {"channel": 1, "patch": {"name": "rewritten", "pattern": compact("F#5 . A2")}}, fade=0)
        self.assertFalse(engine.status()["channels"][0]["active"])
        engine.schedule("restart", {"channel": 1}, fade=0)
        engine.render(2000)
        state = engine.status()
        self.assertTrue(state["channels"][0]["active"])
        self.assertEqual(state["channels"][0]["name"], "rewritten")
        self.assertGreater(engine.channels[1].last_trigger_frame, survivor_frame)
        applied = [entry for entry in state["history"] if entry["phase"] == "applied"]
        self.assertTrue(any(entry["kind"] == "kill" for entry in applied))
        self.assertTrue(any(entry["kind"] == "restart" for entry in applied))
        rewrite = next(entry for entry in applied if entry["kind"] == "set" and entry["decision"].get("name") == "rewritten")
        self.assertEqual(rewrite["decision"]["pattern_steps"], 3)

    def test_lane_modulation_is_visible_in_compact_state(self):
        engine = self.make_engine()
        engine.schedule(
            "set",
            {
                "channel": 4,
                "patch": {
                    "pattern": compact("C2"),
                    "synth": {"waveform": "noise", "modulation": {"target": "pan", "rate_hz": 5, "depth": 0.8}},
                },
            },
            fade=0,
        )
        audio = engine.render(2000)
        self.assertGreater(max(abs(value) for value in audio), 0.01)
        compact_state = engine.compact_status(history_limit=4)
        self.assertEqual(compact_state["channels"][3]["modulation"], "pan")
        self.assertTrue(compact_state["history"])

    def test_system_random_seed_is_resolved_once_and_reproducible(self):
        patch = {
            "pattern": compact("C3 C3 C3 C3"),
            "step_beats": 0.125,
            "synth": {"waveform": "noise"},
        }
        system_engine = self.make_engine()
        with mock.patch.object(synth_module._SYSTEM_RANDOM, "getrandbits", return_value=987654321):
            system_engine.schedule(
                "set",
                {"channel": 1, "patch": {**patch, "random_seed": "system"}},
                fade=0,
            )
        explicit_engine = self.make_engine()
        explicit_engine.schedule(
            "set",
            {"channel": 1, "patch": {**patch, "random_seed": 987654321}},
            fade=0,
        )
        expected_seed = "0x0000000000000000000000003ade68b1"
        self.assertEqual(system_engine.status()["channels"][0]["random_seed"], expected_seed)
        self.assertEqual(list(system_engine.render(2000)), list(explicit_engine.render(2000)))
        history = system_engine.status()["history"]
        seeded = next(entry for entry in history if entry["phase"] == "scheduled")
        self.assertEqual(seeded["decision"]["random_seed"], expected_seed)

    def test_v2_fresh_system_domains_resolve_once_and_are_auditable(self):
        engine = self.make_engine()
        with mock.patch(
            "mcfa.providers.system.os.urandom",
            side_effect=[(0x1111).to_bytes(16, "big"), (0x2222).to_bytes(16, "big")],
        ):
            engine.schedule(
                "set",
                {
                    "channel": 1,
                    "patch": {
                        "rng": {
                            "decision": {"mode": "fresh", "algorithm": "philox", "source": "system"},
                            "sound": {"mode": "fresh", "algorithm": "chacha20", "source": "system"},
                        }
                    },
                },
                fade=0,
            )
        rng = engine.status()["channels"][0]["rng"]
        self.assertEqual(rng["decision"]["seed"], "0x00000000000000000000000000001111")
        self.assertEqual(rng["sound"]["seed"], "0x00000000000000000000000000002222")
        history_rng = engine.status()["history"][0]["decision"]["rng"]
        self.assertEqual(history_rng["decision"]["seed"], "0x00000000000000000000000000001111")
        self.assertEqual(history_rng["sound"]["seed"], "0x00000000000000000000000000002222")

    def test_v2_fresh_tsotchke_seed_is_resolved_off_audio_thread(self):
        from mcfa.providers import EntropyChunk

        chunk = EntropyChunk(
            data=bytes.fromhex("00112233445566778899aabbccddeeff"),
            provider="tsotchke-local",
            execution="local-state-vector-simulation",
            entropy_origin="conditioned-host-os-cpu",
            engine_version="3.0.0",
            source_revision="1a77e77",
        )
        engine = self.make_engine()
        with mock.patch("mcfa.providers.tsotchke.read_tsotchke_entropy", return_value=chunk) as read:
            engine.schedule(
                "set",
                {
                    "channel": 1,
                    "patch": {
                        "rng": {
                            "sound": {
                                "mode": "fresh",
                                "algorithm": "chacha20",
                                "source": "tsotchke-local",
                            }
                        }
                    },
                },
                fade=0,
            )
        read.assert_called_once_with(16)
        sound = engine.status()["channels"][0]["rng"]["sound"]
        self.assertEqual(sound["source_label"], "Decoherence Engine")
        self.assertEqual(sound["seed"], "0x00112233445566778899aabbccddeeff")
        self.assertEqual(sound["provenance"]["source_revision"], "1a77e77")

    def test_v2_noise_consumption_does_not_perturb_decision_stream(self):
        rng = {
            "decision": {"mode": "seeded", "algorithm": "philox", "seed": 1234},
            "sound": {"mode": "seeded", "algorithm": "pcg64dxsm", "seed": 5678},
        }
        noisy = self.make_engine()
        quiet = self.make_engine()
        noisy.schedule(
            "set",
            {
                "channel": 1,
                "patch": {
                    "rng": rng,
                    "pattern": compact("C3 C3 C3 C3"),
                    "synth": {"waveform": "noise"},
                },
            },
            fade=0,
        )
        quiet.schedule(
            "set",
            {
                "channel": 1,
                "patch": {
                    "rng": rng,
                    "pattern": compact("C3 C3 C3 C3"),
                    "synth": {"waveform": "sine"},
                },
            },
            fade=0,
        )
        noisy.render(2000)
        quiet.render(2000)
        self.assertEqual(
            list(noisy.channels[0].decision_rng.random(32)),
            list(quiet.channels[0].decision_rng.random(32)),
        )

    def test_v2_decision_consumption_does_not_perturb_sound_stream(self):
        patch = {
            "rng": {
                "decision": {"mode": "seeded", "algorithm": "chacha20", "seed": 3},
                "sound": {"mode": "seeded", "algorithm": "philox", "seed": 4},
            }
        }
        first = self.make_engine()
        second = self.make_engine()
        first.schedule("set", {"channel": 1, "patch": patch}, fade=0)
        second.schedule("set", {"channel": 1, "patch": patch}, fade=0)
        first.channels[0].decision_rng.random(1000)
        self.assertEqual(
            list(first.channels[0].sound_rng.random(64)),
            list(second.channels[0].sound_rng.random(64)),
        )

    def test_dense_ten_lane_renderer_stays_faster_than_realtime(self):
        if synth_module._np is None:
            self.skipTest("production real-time benchmark requires the installed NumPy runtime")
        engine = SynthEngine(bpm=127, sample_rate=44100, backend_name="benchmark")
        items = []
        for channel in range(1, 11):
            items.append(
                {
                    "channel": channel,
                    "patch": {
                        "pattern": compact("C2 F#5 C6 . A1 D4 . G6"),
                        "clock": "free",
                        "bpm": 53 + channel * 19,
                        "step_beats": 0.11 + channel * 0.013,
                        "volume": 0.04,
                        "synth": {
                            "waveform": "noise" if channel % 2 else "saw",
                            "effects": {"delay_mix": 0.2, "delay_feedback": 0.35, "reverb_mix": 0.2},
                            "modulation": {"target": "pan", "rate_hz": channel * 0.7, "depth": 0.8},
                        },
                    },
                }
            )
        engine.schedule("batch", {"items": items}, fade=0)
        started = time.perf_counter()
        remaining = 44100
        while remaining:
            block = min(1024, remaining)
            engine.render(block)
            remaining -= block
        elapsed = time.perf_counter() - started
        self.assertLess(elapsed, 1.0, f"dense renderer took {elapsed:.3f}s for 1.0s of audio")


if __name__ == "__main__":
    unittest.main()
