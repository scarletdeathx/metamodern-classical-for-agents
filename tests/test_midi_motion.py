import copy
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import mido

from mcfa.dataset import generate_dataset, _facts, _parse, _stats, METRIC_FIELDS, MAX_ATTEMPTS
from mcfa.midi_analysis import analyze_midi
from mcfa.midi_controls import KEYS, SCALES, TIME_SIGNATURES, MidiControls
from mcfa.midi_motion import MotionControls, STEADY_CCS, enforce_contract, generate_motion_midi
from mcfa.midi_motion_verify import verify_motion
from mcfa.providers.base import EntropyProviderError
from mcfa.recipes import load_recipes, parse_recipes

ROOT = Path(__file__).resolve().parents[1]
MOTION = dict(min_notes_per_sec=15, max_gap_s=0.25, tempo_interval_beats=0.25,
              harmony_interval_beats=0.25, cc_interval_beats=0.125,
              pitch_bend_interval_beats=0.125, chord_sizes=[2, 3, 4])


def fake_draw(n, lane, tag="test"):
    return hashlib.shake_256(f"{tag}/{lane}".encode()).digest(n), {"provider": "fixture"}


def to_bytes(mid):
    buf = io.BytesIO()
    mid.save(file=buf)
    return buf.getvalue()


class MotionTests(unittest.TestCase):
    def generate(self, **kwargs):
        return generate_motion_midi(2, 8, MidiControls(tempo=120, programs=[40, 80], velocity=(1, 127),
            rest_probability=kwargs.pop("rest_probability", 0.01), time_signature=kwargs.pop("meter", "4/4")),
            kwargs.pop("motion", MOTION), lambda n, lane: fake_draw(n, lane),
            duration=kwargs.pop("duration", 6), tempo_range=(20, 400), **kwargs)

    def test_density_and_gap_despite_high_rest_probability(self):
        for rest in (0.0, 0.99):
            mid, _ = self.generate(rest_probability=rest)
            parsed = _parse(to_bytes(mid))
            a = analyze_midi(parsed)
            self.assertGreaterEqual(a["metrics"]["notes_per_sec"], 15)
            self.assertLessEqual(a["metrics"]["max_gap_s"], 0.25)
            self.assertEqual(a["metrics"]["max_gap_s"], 0)
            self.assertLessEqual(a["max_onset_gap_s"], 0.25)

    def test_every_meter_and_duration(self):
        for meter in TIME_SIGNATURES:
            with self.subTest(meter=meter):
                mid, _ = self.generate(meter=meter)
                self.assertLessEqual(abs(mid.length - 6), 2)
                self.assertGreaterEqual(analyze_midi(mid)["metrics"]["notes_per_sec"], 15)

    def test_frequent_tempo_key_chord_changes(self):
        mid, prov = self.generate()
        a = analyze_midi(mid)
        self.assertGreater(len(a["tempos"]), 20)
        self.assertTrue(all(t % 120 == 0 for t, _ in a["tempos"]))
        self.assertTrue(all(b-a == 120 for (a, _), (b, _) in zip(a["tempos"], a["tempos"][1:])))
        self.assertTrue(all(20 <= 60_000_000/t <= 400 for _, t in a["tempos"]))
        self.assertEqual(len(a["key_events"]), len(prov["harmony"]))
        self.assertGreater(len(prov["harmony"]), 20)
        for first, second in zip(prov["harmony"], prov["harmony"][1:]):
            self.assertNotEqual(first["key"], second["key"])
            self.assertNotEqual(first["chord"], second["chord"])
        self.assertTrue(all(e["key"] in KEYS and e["scale"] in SCALES for e in prov["harmony"]))
        row = _facts(to_bytes(mid), 0)
        row.update(lanes=prov["lane_layout"], motion=prov["motion"])
        result = verify_motion(_parse(to_bytes(mid)), row, {"sha256": row["sha256"], "params": {
            "harmony": prov["harmony"], "tempo_map_ticks": prov["tempo_map_ticks"], "controls": {"velocity": [1, 127]}}})
        self.assertGreater(result["harmony_change_count"], 20)

    def test_allowed_automation_only_and_programs_fixed(self):
        mid, _ = self.generate()
        a = analyze_midi(mid)
        self.assertEqual(set(a["cc_counts"]), {1, 91, 93})
        self.assertFalse(set(a["cc_counts"]) & set(STEADY_CCS))
        self.assertGreater(len(a["bend_events"]), 100)
        self.assertGreater(len(a["velocity_values"]), 20)
        self.assertEqual(a["program_events"], [(0, 0, 40), (0, 1, 80)])
        for lane in range(2):
            self.assertTrue(all(t % 60 == 0 for t, ch, _, _ in a["cc_events"] if ch == lane))
            self.assertTrue(all(-8192 <= value <= 8191 for _, _, value in a["bend_events"]))

    def test_contract_rejects_low_density_and_long_silence(self):
        mid = mido.MidiFile()
        mid.tracks.append(mido.MidiTrack([
            mido.Message("note_on", channel=0, note=60, velocity=90, time=960),
            mido.Message("note_off", channel=0, note=60, velocity=0, time=480),
            mido.MetaMessage("end_of_track", time=960)]))
        parsed = _parse(to_bytes(mid))
        with self.assertRaisesRegex(ValueError, "density"):
            enforce_contract(parsed, MotionControls(min_notes_per_sec=15).validate())
        with self.assertRaisesRegex(ValueError, "silence"):
            enforce_contract(parsed, MotionControls(max_gap_s=0.25).validate())
        # Silence counts leading/trailing time; simultaneous chords do not mask it.
        self.assertEqual(analyze_midi(parsed)["metrics"]["max_gap_s"], 1)

    def test_density_and_gap_controls_work_without_other_motion(self):
        mid, _ = generate_motion_midi(1, 2, MidiControls(tempo=20, programs=[0]),
            {"min_notes_per_sec": 15, "max_gap_s": 0.25}, lambda n, lane: fake_draw(n, lane))
        a = analyze_midi(mid)
        self.assertGreaterEqual(a["metrics"]["notes_per_sec"], 15)
        self.assertEqual(a["metrics"]["max_gap_s"], 0)
        self.assertEqual(a["cc_counts"], {})
        self.assertEqual(a["bend_events"], [])

    def test_entropy_failure_aborts_without_retry_or_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            failed = mock.Mock(side_effect=EntropyProviderError("Mac drawd unavailable"))
            with self.assertRaisesRegex(EntropyProviderError, "Mac drawd unavailable"):
                generate_dataset(Path(tmp)/"ds", 1, motion=MOTION, duration=6, draw_fn=failed)
            self.assertEqual(failed.call_count, 1)
            self.assertFalse(list(Path(tmp).rglob("*.mid")))

    def test_manifest_metrics_log_labels_resume_and_rebuild(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, log = Path(tmp)/"ds", Path(tmp)/"log.jsonl"
            recipes = parse_recipes([{"name": "forbidden-nightmare-recipe", "count": 2,
                "fixed": {"duration": 6, "tempo_change_range": [20, 400], "programs": [0, 127],
                          "preset": "forbidden-nightmare-preset", "motion": MOTION}}])
            generate_dataset(root, recipes=recipes, draw_fn=fake_draw, log=log, lanes=2)
            rows = [json.loads(line) for line in (root/"manifest.jsonl").read_text().splitlines()]
            self.assertEqual({p.name for p in root.iterdir()}, {"manifest.jsonl", "midi"})
            for row in rows:
                self.assertTrue(METRIC_FIELDS <= row.keys())
                data = (root/row["path"]).read_bytes()
                for label in (b"forbidden-nightmare-recipe", b"forbidden-nightmare-preset", b"eshkol", b"moonlab", b"rngoddess"):
                    self.assertNotIn(label, data.lower())
            before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in root.rglob("*.mid")}
            summary = generate_dataset(root, recipes=recipes, resume=True, draw_fn=mock.Mock(side_effect=AssertionError("unexpected draw")), lanes=2)
            self.assertEqual(summary["skipped"], 2)
            self.assertTrue(all((p.read_bytes(), p.stat().st_mtime_ns)==snapshot for p, snapshot in before.items()))
            (root/"manifest.jsonl").unlink()
            generate_dataset(root, recipes=recipes, resume=True, draw_fn=mock.Mock(side_effect=AssertionError("unexpected draw")), lanes=2)
            rebuilt = [json.loads(line) for line in (root/"manifest.jsonl").read_text().splitlines()]
            self.assertEqual([r["notes_per_sec"] for r in rebuilt], [r["notes_per_sec"] for r in rows])
            self.assertEqual([r["recipe"] for r in rebuilt], ["forbidden-nightmare-recipe"]*2)
            self.assertTrue(all(r["key"] is None and r["scale"] is None for r in rebuilt))

    def test_dataset_rechecks_serialized_density_before_accepting(self):
        mid = mido.MidiFile()
        mid.tracks.append(mido.MidiTrack([
            mido.Message("program_change", program=0),
            mido.Message("note_on", note=60, velocity=90),
            mido.Message("note_off", note=60, velocity=0, time=4*480),
            mido.MetaMessage("end_of_track")]))
        motion = MotionControls(min_notes_per_sec=15).validate().public()
        prov = {"bars": 1, "draws": [], "lane_layout": [], "motion": motion,
                "harmony": [], "tempo_map_ticks": [(0, 500000)], "tempo_draw": None, "harmony_draw": None}
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch("mcfa.midi_motion.generate_motion_midi", return_value=(mid, prov)):
                with self.assertRaisesRegex(RuntimeError, "rejected"):
                    generate_dataset(Path(tmp)/"ds", 1, motion={"min_notes_per_sec": 15}, draw_fn=fake_draw)
            self.assertFalse(list(Path(tmp).rglob("*.mid")))
            self.assertEqual((Path(tmp)/"ds/manifest.jsonl").read_text(), "")

    def test_recipe_count_and_full_choices(self):
        recipes = load_recipes(ROOT/"recipes/nightmare-60s.yaml")
        self.assertEqual(len(recipes), 1)
        r = recipes[0]
        self.assertEqual((r.name, r.count), ("nightmare-60s", 1000))
        self.assertEqual(r.fixed["duration"], 60)
        motion = MotionControls(**r.fixed["motion"]).validate()
        self.assertEqual(set(motion.harmony_keys), set(KEYS))
        self.assertEqual(set(motion.harmony_scales), set(SCALES))
        self.assertEqual(set(r.vary.time_signatures), set(TIME_SIGNATURES))
        self.assertEqual((motion.min_notes_per_sec, motion.max_gap_s), (15, 0.25))

    def test_verifier_rejects_forbidden_controller_and_midpiece_program(self):
        mid, prov = self.generate()
        row = _facts(to_bytes(mid), 0)
        row.update(lanes=prov["lane_layout"], motion=prov["motion"])
        for msg, reason in ((mido.Message("control_change", channel=0, control=7, value=80), "metric|steady"),
                            (mido.Message("program_change", channel=0, program=12), "mid-piece")):
            changed = _parse(to_bytes(mid))
            # Insert a zero-delta event after the first positive tick without changing timing.
            index = next(i for i, m in enumerate(changed.tracks[0]) if m.time > 0)
            changed.tracks[0].insert(index+1, msg)
            with self.assertRaisesRegex(ValueError, reason):
                verify_motion(changed, row)

    def test_validation_rejects_incompatible_options(self):
        for options in ({"tempo_interval_beats": 0.0001}, {"min_notes_per_sec": float("nan")},
                        {"max_gap_s": -1}, {"harmony_interval_beats": 0.25, "harmony_keys": ["C"]}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                MotionControls(**options).validate()
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, "without bar-based"):
                generate_dataset(Path(tmp)/"ds", 1, motion=MOTION, tempo_changes=2, draw_fn=fake_draw)


if __name__ == "__main__":
    unittest.main()
