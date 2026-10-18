import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

try:
    import mido  # noqa: F401
except ImportError:  # pragma: no cover
    mido = None

from mcfa import dataset


def fake_draw(n, lane, tag):
    seed = hashlib.sha256(f"{tag}/{lane}".encode()).digest()
    data = hashlib.shake_256(seed).digest(n)
    return data, {"provider": "fake", "manifest": {"contributors": [{"source": "fake", "bytes": n}]}}


def constant_draw(n, lane, tag):
    return bytes([200]) * n, {"provider": "constant"}


@unittest.skipIf(mido is None, "mido not installed")
class DatasetTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())

    def gen(self, count, **kw):
        kw.setdefault("draw_fn", fake_draw)
        return dataset.generate_dataset(self.dir, count, lanes=2, bars=2, **kw)

    def test_layout_and_metadata(self):
        s = self.gen(3)
        self.assertEqual(s["pieces"], 3)
        for i in range(3):
            self.assertTrue((self.dir / "midi" / f"{i:06d}.mid").is_file())
            meta = json.loads((self.dir / "meta" / f"{i:06d}.json").read_text())
            for key in ("schema", "id", "params", "source", "midi_sha256", "notes", "duration_s",
                        "tracks", "lanes_provenance", "generator", "seed_label"):
                self.assertIn(key, meta)
            data = (self.dir / "midi" / f"{i:06d}.mid").read_bytes()
            self.assertEqual(meta["midi_sha256"], hashlib.sha256(data).hexdigest())
            self.assertEqual(meta["tracks"], 2)
            self.assertGreater(meta["notes"], 0)
            self.assertEqual(len(meta["lanes_provenance"]), 2)
            self.assertIn("manifest", meta["lanes_provenance"][0])
        lines = (self.dir / "manifest.jsonl").read_text().splitlines()
        self.assertEqual(len(lines), 3)
        card = (self.dir / "dataset_card.md").read_text()
        self.assertIn("Pieces: 3", card)
        self.assertFalse(list(self.dir.rglob("*.tmp")))

    def test_resume_skips_done_and_refuses_without_flag(self):
        self.gen(2)
        before = (self.dir / "midi" / "000000.mid").stat().st_mtime_ns
        with self.assertRaises(FileExistsError):
            self.gen(3)
        s = self.gen(3, resume=True)
        self.assertEqual((s["made"], s["skipped"], s["pieces"]), (1, 2, 3))
        self.assertEqual((self.dir / "midi" / "000000.mid").stat().st_mtime_ns, before)

    def test_atomic_write_leaves_no_partial_file(self):
        target = self.dir / "x.bin"
        with mock.patch("os.replace", side_effect=OSError("boom")):
            with self.assertRaises(OSError):
                dataset.atomic_write(target, b"data")
        self.assertFalse(target.exists())
        self.assertEqual(list(self.dir.iterdir()), [])
        dataset.atomic_write(target, b"data")
        self.assertEqual(target.read_bytes(), b"data")

    def test_validation_rejects_broken(self):
        with self.assertRaises(ValueError):
            dataset.validate_midi(b"MThd garbage")
        import io
        mid = mido.MidiFile()
        mid.tracks.append(mido.MidiTrack())
        buf = io.BytesIO()
        mid.save(file=buf)
        with self.assertRaisesRegex(ValueError, "empty"):
            dataset.validate_midi(buf.getvalue())

    def test_invalid_piece_is_regenerated_and_logged(self):
        real = dataset.validate_midi
        calls = {"n": 0}

        def flaky(data):
            calls["n"] += 1
            if calls["n"] == 1:
                raise ValueError("malformed MIDI: injected")
            return real(data)
        with mock.patch.object(dataset, "validate_midi", side_effect=flaky):
            s = self.gen(1)
        self.assertEqual((s["pieces"], s["rejected"]), (1, 1))
        rej = [json.loads(l) for l in (self.dir / "rejects.jsonl").read_text().splitlines()]
        self.assertIn("injected", rej[0]["reason"])
        meta = json.loads((self.dir / "meta" / "000000.json").read_text())
        self.assertEqual(meta["attempt"], 2)

    def test_dedupe_by_sha(self):
        with self.assertRaisesRegex(RuntimeError, "rejected"):
            self.gen(2, draw_fn=constant_draw)  # identical entropy -> identical MIDI
        rej = [json.loads(l) for l in (self.dir / "rejects.jsonl").read_text().splitlines()]
        self.assertTrue(all(r["reason"].startswith("duplicate of 000000") for r in rej))
        self.assertEqual(len(list((self.dir / "meta").glob("*.json"))), 1)

    def test_vary_logs_draw(self):
        self.gen(2, vary=True, lanes_range=(1, 3), bars_range=(2, 3))
        meta = json.loads((self.dir / "meta" / "000000.json").read_text())
        self.assertTrue(1 <= meta["params"]["lanes"] <= 3)
        self.assertIn("vary_draw", meta["params"])
        self.assertEqual(meta["tracks"], meta["params"]["lanes"])


if __name__ == "__main__":
    unittest.main()
