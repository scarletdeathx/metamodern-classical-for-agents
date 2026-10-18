import hashlib
import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path

try:
    import mido
except ImportError:  # pragma: no cover
    mido = None

from mcfa import dataset
from mcfa.midi_controls import (KEYS, ROLE_RANGES, SCALES, MidiControls, VarySpec, canonical_key,
                                canonical_scale, midi_channel, parse_range, vary_controls)
from mcfa.model import ValidationError

_spec = importlib.util.spec_from_file_location(
    "eshkol_midi", Path(__file__).resolve().parents[1] / "tools" / "eshkol_midi.py")
eshkol_midi = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(eshkol_midi)


def fake_draw(n, lane, tag="t"):
    return hashlib.shake_256(f"{tag}/{lane}".encode()).digest(n), {"provider": "fake"}


def notes_of(mid):
    out = []
    for ti, t in enumerate(mid.tracks):
        for m in t:
            if m.type == "note_on" and m.velocity > 0:
                out.append((ti, m.note, m.velocity, m.channel))
    return out


class ControlParsingTests(unittest.TestCase):
    def test_names(self):
        self.assertEqual(canonical_scale("Major"), "ionian")
        self.assertEqual(canonical_scale("minor"), "aeolian")
        self.assertEqual(canonical_scale("octatonic"), "diminished")
        self.assertEqual(canonical_key("Bb"), "A#")
        self.assertEqual(parse_range("C2-C4"), (36, 60))
        self.assertEqual(midi_channel(9), 10)
        for bad in (lambda: canonical_scale("bebop"), lambda: canonical_key("H"),
                    lambda: MidiControls(tempo=500).validate(),
                    lambda: MidiControls(time_signature="4/5").validate(),
                    lambda: MidiControls(scale="major-pentatonic", key="C", lane_ranges=[(61, 61)]).validate()):
            with self.subTest(), self.assertRaises(ValidationError):
                bad()

    def test_palette_modes_present(self):
        for name in ("ionian", "dorian", "phrygian", "lydian", "mixolydian", "aeolian", "locrian",
                     "harmonic-minor", "melodic-minor", "major-pentatonic", "minor-pentatonic",
                     "whole-tone", "diminished", "chromatic"):
            self.assertIn(name, SCALES)


@unittest.skipIf(mido is None, "mido not installed")
class GenerationTests(unittest.TestCase):
    def gen(self, controls, lanes=4, bars=4, tag="t"):
        return eshkol_midi.generate_midi(lanes, bars, controls=controls,
                                         draw_fn=lambda n, lane: fake_draw(n, lane, tag))

    def test_notes_in_scale_and_range_for_every_scale(self):
        for scale in SCALES:
            for key in ("C", "F#"):
                c = MidiControls(scale=scale, key=key)
                mid, prov = self.gen(c)
                classes = {(KEYS.index(c.key) + i) % 12 for i in SCALES[c.scale]}
                notes = notes_of(mid)
                self.assertTrue(notes)
                for ti, note, vel, ch in notes:
                    lo, hi = c.lane_range(ti)
                    self.assertIn(note % 12, classes, (scale, key, note))
                    self.assertTrue(lo <= note <= hi)
                    self.assertTrue(40 <= vel <= 110)
                    self.assertNotEqual(ch, 9)

    def test_meta_events_lengths_and_programs(self):
        c = MidiControls(tempo=90, time_signature="7/8", programs=[33, 0], lengths=(0.5,))
        mid, prov = self.gen(c, lanes=2, bars=3)
        metas = {m.type: m for m in mid.tracks[0] if m.is_meta}
        self.assertEqual(round(mido.tempo2bpm(metas["set_tempo"].tempo)), 90)
        self.assertEqual((metas["time_signature"].numerator, metas["time_signature"].denominator), (7, 8))
        progs = [m.program for t in mid.tracks for m in t if m.type == "program_change"]
        self.assertEqual(progs, [33, 0])
        # 3 bars of 7/8 = 10.5 quarter beats -> every lane ends exactly there
        for t in mid.tracks:
            self.assertEqual(sum(m.time for m in t), round(10.5 * 480))
        self.assertEqual(prov["lane_layout"][0]["role"], "bass")
        self.assertEqual(prov["lane_layout"][1]["range"], list(ROLE_RANGES["tenor"]))

    def test_deterministic_with_fake_source(self):
        a, b = io.BytesIO(), io.BytesIO()
        self.gen(MidiControls(scale="dorian"))[0].save(file=a)
        self.gen(MidiControls(scale="dorian"))[0].save(file=b)
        self.assertEqual(a.getvalue(), b.getvalue())
        c = io.BytesIO()
        self.gen(MidiControls(scale="dorian"), tag="other")[0].save(file=c)
        self.assertNotEqual(a.getvalue(), c.getvalue())

    def test_legacy_matches_original_mapping(self):
        mid, prov = eshkol_midi.generate_midi(2, 2, legacy=True, draw_fn=lambda n, lane: fake_draw(n, lane))
        self.assertTrue(prov["legacy"])
        self.assertFalse(any(m.is_meta and m.type == "set_tempo" for m in mid.tracks[0]))
        data = fake_draw(2 * 4 * 4 * 4, 0)[0]
        expected = [n["pitch"] for n in eshkol_midi.bytes_to_notes(data, 0) if n["start_tick"] < 2 * 4 * 480]
        got = [m.note for m in mid.tracks[0] if m.type == "note_on" and m.velocity > 0]
        self.assertEqual(got, expected[:len(got)])

    def test_vary_controls_draws_from_bytes(self):
        spec = VarySpec(tempo_range=(60, 140), scales=["dorian", "lydian"], keys=list(KEYS),
                        time_signatures=["4/4", "7/8"], rest_range=(0.0, 0.5))
        c, lanes, bars, drawn = vary_controls(MidiControls(), spec, bytes(range(16)), 4, 8)
        self.assertEqual(set(drawn), {"tempo", "scale", "key", "time_signature", "rest_probability"})
        self.assertEqual(drawn["scale"], "dorian")  # byte 2 % 2 == 0
        self.assertEqual(drawn["key"], "D#")  # byte 3
        self.assertTrue(60 <= c.tempo <= 140)


@unittest.skipIf(mido is None, "mido not installed")
class DatasetVaryTests(unittest.TestCase):
    def test_vary_logged_and_carded(self):
        d = Path(tempfile.mkdtemp())
        spec = VarySpec(tempo_range=(60, 140), scales=["dorian", "aeolian", "lydian"], keys=list(KEYS))
        dataset.generate_dataset(d, 4, lanes=2, bars=2, vary=True, vary_spec=spec,
                                 lanes_range=(2, 3), bars_range=(2, 2), draw_fn=fake_draw)
        for p in sorted((d / "meta").glob("*.json")):
            m = json.loads(p.read_text())
            drawn = m["params"]["vary_draw"]["drawn"]
            self.assertTrue({"tempo", "scale", "key", "lanes", "bars"} <= set(drawn))
            ctl = m["params"]["controls"]
            self.assertEqual((ctl["tempo"], ctl["scale"], ctl["key"]), (drawn["tempo"], drawn["scale"], drawn["key"]))
            mid = mido.MidiFile(d / m["midi"])
            classes = {(KEYS.index(ctl["key"]) + i) % 12 for i in SCALES[ctl["scale"]]}
            for ti, note, _, _ in notes_of(mid):
                lo, hi = m["lane_layout"][ti]["range"]
                self.assertIn(note % 12, classes)
                self.assertTrue(lo <= note <= hi)
        card = (d / "dataset_card.md").read_text()
        self.assertIn("## Musical controls", card)
        self.assertIn("Tempo (BPM)", card)

    def test_legacy_dataset(self):
        d = Path(tempfile.mkdtemp())
        dataset.generate_dataset(d, 2, lanes=2, bars=2, legacy=True, draw_fn=fake_draw)
        m = json.loads((d / "meta" / "000000.json").read_text())
        self.assertTrue(m["params"]["legacy"])
        self.assertIsNone(m["params"]["controls"])


if __name__ == "__main__":
    unittest.main()
