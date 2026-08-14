import unittest

from mcfa.model import Channel, ValidationError, midi_to_note, note_to_midi, parse_pattern, pattern_from_json


class NoteAndPatternTests(unittest.TestCase):
    def test_note_round_trip_and_accidentals(self):
        self.assertEqual(note_to_midi("C3"), 48)
        self.assertEqual(note_to_midi("Bb2"), 46)
        self.assertEqual(note_to_midi("A4"), 69)
        self.assertEqual(midi_to_note(69), "A4")

    def test_compact_pattern_encodes_rhythm_chords_and_articulation(self):
        pattern = parse_pattern("C2 . C3+G3:0.6:0.25:0.5 -")
        self.assertEqual(len(pattern), 4)
        self.assertEqual(pattern[0].notes, [36])
        self.assertEqual(pattern[1].notes, [])
        self.assertEqual(pattern[2].notes, [48, 55])
        self.assertEqual(pattern[2].velocity, 0.6)
        self.assertEqual(pattern[2].gate, 0.25)
        self.assertEqual(pattern[2].probability, 0.5)

    def test_json_pattern_forms(self):
        pattern = pattern_from_json(["C3", None, ["E3", "G3"], {"notes": "D3", "gate": 0.2}])
        self.assertEqual([step.notes for step in pattern], [[48], [], [52, 55], [50]])
        self.assertEqual(pattern[-1].gate, 0.2)

    def test_invalid_pattern_is_rejected(self):
        with self.assertRaises(ValidationError):
            parse_pattern("H3")
        with self.assertRaises(ValidationError):
            parse_pattern("C3:2.0")

    def test_noise_lane_clock_lifecycle_and_modulation_are_validated(self):
        lane = Channel(id=1)
        lane.update(
            {
                "active": False,
                "clock": "free",
                "bpm": 73,
                "synth": {
                    "modulation": {
                        "target": "cutoff",
                        "waveform": "square",
                        "rate_hz": 7.5,
                        "depth": 0.9,
                    }
                },
            }
        )
        self.assertFalse(lane.active)
        self.assertEqual(lane.bpm, 73)
        self.assertEqual(lane.synth.modulation.target, "cutoff")
        with self.assertRaises(ValidationError):
            lane.update({"clock": "approximately"})
        with self.assertRaises(ValidationError):
            lane.update({"synth": {"modulation": {"target": "explode"}}})

    def test_lane_random_seed_is_validated_and_can_return_to_default(self):
        lane = Channel(id=1)
        lane.update({"random_seed": 123456789})
        self.assertEqual(lane.random_seed, 123456789)
        self.assertEqual(lane.public()["random_seed"], "0x000000000000000000000000075bcd15")
        lane.update({"random_seed": "0x1234"})
        self.assertEqual(lane.random_seed, 0x1234)
        lane.update({"random_seed": "default"})
        self.assertIsNone(lane.random_seed)
        for invalid in (-1, 1 << 128, 1.5, True, "system", "12.0", "0xnope"):
            with self.subTest(invalid=invalid), self.assertRaises(ValidationError):
                lane.update({"random_seed": invalid})


if __name__ == "__main__":
    unittest.main()
