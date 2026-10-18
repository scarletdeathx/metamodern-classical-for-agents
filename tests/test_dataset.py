import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

try:
    import mido
except ImportError:
    mido = None

from mcfa import dataset
from mcfa.midi_controls import MidiControls, VarySpec, SCALES, KEYS, TIME_SIGNATURES
from mcfa.recipes import load_recipes, parse_recipes

ROOT = Path(__file__).resolve().parents[1]


def fake_draw(n, lane, tag):
    data = hashlib.shake_256(f"{tag}/{lane}".encode()).digest(n)
    return data, {"provider": "fake", "manifest": {"contributors": [{"source": "fake", "bytes": n}]}}


def constant_draw(n, lane, tag):
    return bytes([200]) * n, {"provider": "constant"}


@unittest.skipIf(mido is None, "mido not installed")
class DatasetTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.dir = self.root / "dataset"
        self.log = self.root / "provenance.jsonl"

    def gen(self, count=1, **kw):
        kw.setdefault("draw_fn", fake_draw)
        kw.setdefault("lanes", 2)
        kw.setdefault("bars", 2)
        return dataset.generate_dataset(self.dir, count, **kw)

    def rows(self):
        return [json.loads(x) for x in (self.dir / "manifest.jsonl").read_text().splitlines()]

    def records(self):
        return [json.loads(x) for x in self.log.read_text().splitlines()]

    def test_layout_and_metadata(self):
        s = self.gen(3)
        self.assertEqual(s["pieces"], 3)
        self.assertEqual({p.name for p in self.dir.iterdir()}, {"midi", "manifest.jsonl"})
        for i, row in enumerate(self.rows()):
            self.assertEqual(set(row), dataset.MANIFEST_FIELDS)
            self.assertEqual(row["path"], f"midi/000/{i:06d}.mid")
            data = (self.dir / row["path"]).read_bytes()
            self.assertEqual(row["sha256"], hashlib.sha256(data).hexdigest())
            self.assertEqual(len(row["lanes"]), 2)
            self.assertGreater(row["note_count"], 0)
        self.assertFalse(list(self.dir.rglob("*.tmp")))

    def test_sharding_boundary(self):
        self.assertEqual(dataset.midi_path(999), "midi/000/000999.mid")
        self.assertEqual(dataset.midi_path(1000), "midi/001/001000.mid")
        # Exercise an actual boundary write without generating 1000 other pieces.
        path = self.dir / dataset.midi_path(1000)
        dataset.atomic_write(path, b"piece")
        self.assertEqual(path.read_bytes(), b"piece")

    def test_resume_skips_done_and_refuses_without_flag(self):
        self.gen(2)
        path = self.dir / dataset.midi_path(0)
        before = path.stat().st_mtime_ns
        with self.assertRaises(FileExistsError):
            self.gen(3)
        s = self.gen(3, resume=True)
        self.assertEqual((s["made"], s["skipped"], s["pieces"]), (1, 2, 3))
        self.assertEqual(path.stat().st_mtime_ns, before)

    def test_rebuild_missing_and_truncated_manifest(self):
        self.gen(3)
        original = self.rows()
        manifest = self.dir / "manifest.jsonl"
        manifest.write_text(json.dumps(original[0]) + '\n{"id": "000001",')
        s = self.gen(3, resume=True)
        self.assertEqual((s["made"], s["skipped"]), (0, 3))
        recovered = self.rows()
        self.assertEqual(recovered[0], original[0])
        self.assertIsNone(recovered[1]["key"])
        self.assertIsNone(recovered[1]["scale"])
        self.assertIsNone(recovered[1]["lanes"][0]["range"])
        self.assertEqual(recovered[1]["duration_s"], original[1]["duration_s"])
        manifest.unlink()
        s = self.gen(4, resume=True)
        self.assertEqual((s["made"], s["skipped"]), (1, 3))
        self.assertEqual(len(self.rows()), 4)

    def test_missing_midi_regenerates_and_stale_hash_loses_intent(self):
        self.gen(3)
        (self.dir / dataset.midi_path(1)).unlink()
        self.assertEqual(self.gen(3, resume=True)["made"], 1)
        rows = self.rows()
        rows[0]["sha256"] = "wrong"
        dataset.atomic_write(self.dir / "manifest.jsonl", ''.join(json.dumps(r) + '\n' for r in rows).encode())
        self.gen(3, resume=True)
        self.assertIsNone(self.rows()[0]["key"])

    def test_atomic_write_leaves_no_partial_file(self):
        target = self.root / "x.bin"
        with mock.patch("os.replace", side_effect=OSError("boom")):
            with self.assertRaises(OSError):
                dataset.atomic_write(target, b"data")
        self.assertFalse(target.exists())
        self.assertFalse(list(self.root.glob("*.tmp")))
        dataset.atomic_write(target, b"data")
        self.assertEqual(target.read_bytes(), b"data")

    def test_validation_rejects_broken(self):
        with self.assertRaises(ValueError):
            dataset.validate_midi(b"MThd garbage")
        mid = mido.MidiFile()
        mid.tracks.append(mido.MidiTrack())
        buf = io.BytesIO()
        mid.save(file=buf)
        with self.assertRaisesRegex(ValueError, "empty"):
            dataset.validate_midi(buf.getvalue())

    def test_invalid_piece_is_regenerated_and_logged(self):
        real, calls = dataset.validate_midi, []
        def flaky(data):
            calls.append(1)
            if len(calls) == 1:
                raise ValueError("malformed MIDI: injected")
            return real(data)
        with mock.patch.object(dataset, "validate_midi", side_effect=flaky):
            s = self.gen(log=self.log)
        self.assertEqual((s["pieces"], s["rejected"]), (1, 1))
        rej = [r for r in self.records() if r["event"] == "reject"]
        self.assertIn("injected", rej[0]["reason"])
        self.assertEqual([r for r in self.records() if r["event"] == "piece"][0]["attempt"], 2)
        self.assertTrue(Path(str(self.log) + ".summary.md").exists())

    def test_dedupe_by_sha_and_after_recovery(self):
        with self.assertRaisesRegex(RuntimeError, "rejected"):
            self.gen(2, draw_fn=constant_draw, log=self.log)
        rej = [r for r in self.records() if r["event"] == "reject"]
        self.assertTrue(all(r["reason"].startswith("duplicate of 000000") for r in rej))
        self.assertEqual(len(self.rows()), 1)
        (self.dir / "manifest.jsonl").unlink()
        with self.assertRaisesRegex(RuntimeError, "rejected"):
            self.gen(2, draw_fn=constant_draw, resume=True)
        self.assertEqual(len(self.rows()), 1)

    def test_log_refusal_including_symlink(self):
        for path in (self.dir, self.dir / "log.jsonl", self.dir / "midi" / "log.jsonl"):
            with self.subTest(path=path), self.assertRaisesRegex(ValueError, "outside"):
                self.gen(log=path)
        self.dir.mkdir()
        link = self.root / "link"
        link.symlink_to(self.dir, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "outside"):
            self.gen(log=link / "log.jsonl")

    def test_logs_off_during_rejections(self):
        with self.assertRaises(RuntimeError):
            self.gen(2, draw_fn=constant_draw)
        self.assertEqual({p.name for p in self.dir.iterdir()}, {"midi", "manifest.jsonl"})

    def test_vary_logs_draw(self):
        self.gen(2, vary=True, lanes_range=(1, 3), bars_range=(2, 3), log=self.log)
        rec = [r for r in self.records() if r["event"] == "piece"][0]
        self.assertTrue(1 <= rec["params"]["lanes"] <= 3)
        self.assertIn("sha256", rec["params"]["vary"])
        self.assertEqual(len(rec["manifest"]["lanes"]), rec["params"]["lanes"])
        self.assertEqual(len(rec["lanes_provenance"]), rec["params"]["lanes"])
        self.assertIn("generator_commit", rec)

    def test_no_labels_anywhere_in_midi(self):
        recipes = parse_recipes([{"name": "forbidden-recipe-label", "count": 2,
                                   "fixed": {"preset": "forbidden-preset-label"}}])
        self.gen(None, recipes=recipes)
        for row in self.rows():
            data = (self.dir / row["path"]).read_bytes()
            for label in (b"forbidden-recipe-label", b"forbidden-preset-label", b"eshkol", b"rngoddess", b"moonlab"):
                self.assertNotIn(label, data.lower())
            mid = mido.MidiFile(file=io.BytesIO(data))
            for lane, track in enumerate(mid.tracks):
                for msg in track:
                    self.assertNotIn(msg.type, ("text", "marker", "lyrics"))
                    if msg.type == "track_name":
                        self.assertEqual(msg.name, f"lane {lane}")

    def test_tempo_automation_and_duration(self):
        c = MidiControls(tempo=120, time_signature="7/8")
        self.gen(5, controls=c, bars=12, tempo_changes=4, tempo_change_range=(40, 220),
                 tempo_max_jump=30, duration=60, log=self.log)
        for row in self.rows():
            mid = mido.MidiFile(self.dir / row["path"])
            self.assertLessEqual(abs(mid.length - 60), 2)
            events, tick = [], 0
            for msg in mid.tracks[0]:
                tick += msg.time
                if msg.type == "set_tempo":
                    self.assertEqual(tick % (3.5 * 480), 0)
                    events.append(mido.tempo2bpm(msg.tempo))
            self.assertEqual(len(events), 5)
            self.assertTrue(all(40 <= x <= 220 for x in events))
            self.assertTrue(all(abs(a-b) <= 30 for a, b in zip(events, events[1:])))
            self.assertEqual(row["tempo"], {"start": events[0], "min": min(events), "max": max(events)})
            for track in mid.tracks:
                self.assertEqual(sum(m.time for m in track), row["bars"] * 3.5 * 480)

    def test_static_duration_and_impossible_target(self):
        self.gen(duration=60)
        self.assertLessEqual(abs(self.rows()[0]["duration_s"] - 60), 2)
        with self.assertRaisesRegex(ValueError, "whole-bar"):
            dataset.generate_dataset(self.root / "impossible", 1, controls=MidiControls(tempo=20, time_signature="5/4"),
                                     duration=67.5, draw_fn=fake_draw)

    def test_entropy_failure_is_fatal_and_no_fallback(self):
        from mcfa.providers.base import EntropyProviderError
        with mock.patch("mcfa.providers.eshkol.read_eshkol_entropy", side_effect=EntropyProviderError("drawd down")):
            with self.assertRaisesRegex(EntropyProviderError, "drawd down"):
                dataset.generate_dataset(self.dir, 1)
        self.assertEqual(self.rows(), [])

    def test_short_draw_is_fatal(self):
        with self.assertRaisesRegex(Exception, "short entropy"):
            self.gen(draw_fn=lambda n, lane, tag: (b"x", {}))

    def test_recipe_counts_and_recovery(self):
        recipes = parse_recipes([{"name": "first", "count": 2}, {"name": "second", "count": 3,
                                 "vary": {"tempo_range": [40, 220]}}])
        self.gen(None, recipes=recipes)
        self.assertEqual([r["recipe"] for r in self.rows()], ["first"]*2 + ["second"]*3)
        (self.dir / "manifest.jsonl").unlink()
        s = self.gen(None, recipes=recipes, resume=True)
        self.assertEqual(s["recipes"], {"first": 2, "second": 3})
        self.assertEqual(s["made"], 0)
        self.assertTrue(all(r["scale"] is None for r in self.rows()))

    def test_shipped_recipe_counts_and_every_control(self):
        canon = load_recipes(ROOT / "recipes/canon.yaml")
        chaos = load_recipes(ROOT / "recipes/chaos-60s.yaml")
        self.assertEqual(len(canon), 10)
        self.assertEqual([r.count for r in canon], [10]*10)
        self.assertEqual((len(chaos), chaos[0].count), (1, 100))
        c = chaos[0]
        self.assertEqual(c.fixed["duration"], 60)
        self.assertEqual(set(c.vary.scales), set(SCALES))
        self.assertEqual(set(c.vary.keys), set(KEYS))
        self.assertEqual(set(c.vary.time_signatures), set(TIME_SIGNATURES))
        self.assertEqual({p for x in c.vary.program_choices for p in x}, set(range(128)))
        self.assertTrue(all(v is not None for k, v in vars(c.vary).items() if k != "bars_range"))

    def test_duration_rejects_and_redraws_infeasible_tempo_map(self):
        def draw(n, lane, tag):
            if tag == "piece-000000" and lane < 0:
                return bytes(n), {"provider": "fake"}
            return fake_draw(n, lane, tag)
        self.gen(1, controls=MidiControls(time_signature="12/8"),
                 vary=True, vary_spec=VarySpec(tempo_range=(40, 220)),
                 lanes_range=(2, 2), bars_range=(8, 8), tempo_changes=1,
                 tempo_change_range=(40, 220), duration=60, draw_fn=draw, log=self.log)
        rejects = [r for r in self.records() if r["event"] == "reject"]
        self.assertTrue(rejects)
        self.assertIn("whole-bar", rejects[0]["reason"])
        self.assertLessEqual(abs(self.rows()[0]["duration_s"] - 60), 2)

    def test_json_recipes_and_zero_jump(self):
        path = self.root / "recipes.json"
        path.write_text(json.dumps({"recipes": [{"name": "steady", "count": 2,
            "fixed": {"tempo": 120.1, "tempo_changes": 1, "tempo_change_range": [40, 220],
                      "tempo_max_jump": 0, "bars": 4}}]}))
        self.gen(None, recipes=path)
        for row in self.rows():
            mid = mido.MidiFile(self.dir / row["path"])
            values = [m.tempo for m in mid.tracks[0] if m.type == "set_tempo"]
            self.assertEqual(len(values), 2)
            self.assertEqual(values[0], values[1])
            self.assertEqual(set(row["tempo"]), {"start"})

    def test_verifier_detects_manifest_note_count_corruption(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("verify_dataset", ROOT / "tools/verify_dataset.py")
        verifier = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(verifier)
        self.gen(1, log=self.log)
        self.assertEqual(verifier.verify_dataset(self.dir, log=self.log)["compliance_percent"], 100)
        row = self.rows()[0]
        row["note_count"] += 1
        dataset.atomic_write(self.dir / "manifest.jsonl", (json.dumps(row) + "\n").encode())
        with self.assertRaisesRegex(ValueError, "note count"):
            verifier.verify_dataset(self.dir)

    def test_recipe_rejects_invalid_configuration_before_draw(self):
        for item in ([{"name": "a", "count": 0}], [{"name": "a", "count": 1, "vary": {"typo": [1, 2]}}],
                     [{"name": "a", "count": 1, "vary": {"tempo_range": [220, 40]}}]):
            with self.subTest(item=item), self.assertRaises(ValueError):
                parse_recipes(item)


if __name__ == "__main__":
    unittest.main()
