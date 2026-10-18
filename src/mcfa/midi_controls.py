"""Musical controls for the Eshkol MIDI path (tempo, metre, key, scale, ranges).

Vocabulary is reused from MCFA where it exists:
  * scale ids follow PERFORMANCE_PALETTES.md "Mode and pitch-language menu"
    (ionian/major ... chromatic, atonal); "detuned tonal" and "several competing
    modes" are not expressible as a fixed MIDI pitch set and are omitted;
  * tempo is validated with model.validate_bpm (20..400 BPM, MCFA's lane range);
  * note names are parsed/printed with model.note_to_midi / midi_to_note (C3, F#4);
  * note lengths are expressed in beats, like MCFA's Step/step_beats.
New here: lane roles with default registers, time signatures, rest probability,
velocity range, note-length sets and GM programs.

Every choice is made from entropy bytes supplied by the caller (the drawd /
RNGoddess path); this module never uses Python's random.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from .model import ValidationError, midi_to_note, note_to_midi, validate_bpm

TICKS_PER_BEAT = 480  # quarter-note ticks, unchanged from tools/eshkol_midi.py

# Interval sets (semitones above the root). Aliases map to canonical ids.
SCALES: dict[str, tuple[int, ...]] = {
    "ionian": (0, 2, 4, 5, 7, 9, 11),
    "dorian": (0, 2, 3, 5, 7, 9, 10),
    "phrygian": (0, 1, 3, 5, 7, 8, 10),
    "lydian": (0, 2, 4, 6, 7, 9, 11),
    "mixolydian": (0, 2, 4, 5, 7, 9, 10),
    "aeolian": (0, 2, 3, 5, 7, 8, 10),
    "locrian": (0, 1, 3, 5, 6, 8, 10),
    "harmonic-minor": (0, 2, 3, 5, 7, 8, 11),
    "melodic-minor": (0, 2, 3, 5, 7, 9, 11),
    "major-pentatonic": (0, 2, 4, 7, 9),
    "minor-pentatonic": (0, 3, 5, 7, 10),
    "whole-tone": (0, 2, 4, 6, 8, 10),
    "diminished": (0, 2, 3, 5, 6, 8, 9, 11),  # whole-half octatonic
    "chromatic": tuple(range(12)),
    "atonal": tuple(range(12)),  # free pitch: all 12 classes, no tonal centre implied
}
SCALE_ALIASES = {
    "major": "ionian", "minor": "aeolian", "natural-minor": "aeolian",
    "pentatonic": "major-pentatonic", "octatonic": "diminished", "wholetone": "whole-tone",
}
KEYS = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")
_FLATS = {"DB": "C#", "EB": "D#", "GB": "F#", "AB": "G#", "BB": "A#"}
TIME_SIGNATURES = ("4/4", "3/4", "2/4", "5/4", "6/8", "7/8", "12/8")

# Lane roles cycle bass, tenor, alto, soprano (SATB-style registers, MIDI notes).
ROLES = ("bass", "tenor", "alto", "soprano")
ROLE_RANGES = {"bass": (36, 60), "tenor": (48, 67), "alto": (55, 74), "soprano": (60, 84)}
DEFAULT_LENGTHS = (0.25, 0.5, 1.0, 2.0)  # beats: sixteenth, eighth, quarter, half


def canonical_scale(name: str) -> str:
    key = str(name).strip().lower().replace("_", "-").replace(" ", "-")
    key = SCALE_ALIASES.get(key, key)
    if key not in SCALES:
        raise ValidationError(f"unknown scale {name!r}; use one of {sorted(SCALES) + sorted(SCALE_ALIASES)}")
    return key


def canonical_key(name: str) -> str:
    text = str(name).strip()
    up = text[:1].upper() + text[1:]
    if up.upper() in _FLATS:
        return _FLATS[up.upper()]
    if up.upper() in KEYS:
        return up.upper()
    raise ValidationError(f"unknown key {name!r}; use C, C#, Db ... B")


def parse_time_signature(text: str) -> tuple[int, int]:
    try:
        num, den = (int(x) for x in str(text).split("/"))
    except ValueError as exc:
        raise ValidationError(f"time signature must look like 4/4, got {text!r}") from exc
    if not 1 <= num <= 32 or den not in (1, 2, 4, 8, 16, 32):
        raise ValidationError(f"unsupported time signature {text!r}")
    return num, den


def parse_range(text: str) -> tuple[int, int]:
    """'C2-G4' or '36-67' -> (36, 67)."""
    lo, sep, hi = str(text).strip().partition("-")
    if not sep:
        raise ValidationError(f"range must be LOW-HIGH, got {text!r}")
    a, b = note_to_midi(lo), note_to_midi(hi)
    if a > b:
        raise ValidationError(f"range low > high in {text!r}")
    return a, b


@dataclass
class MidiControls:
    tempo: float = 120.0
    time_signature: str = "4/4"
    key: str = "C"
    scale: str = "aeolian"
    rest_probability: float = 0.15
    velocity: tuple[int, int] = (40, 110)
    lengths: tuple[float, ...] = DEFAULT_LENGTHS
    lane_ranges: list[tuple[int, int]] | None = None  # None = role defaults
    programs: list[int] | None = None  # GM program 0..127 per lane (cycled)

    def validate(self) -> "MidiControls":
        self.tempo = validate_bpm(self.tempo)
        parse_time_signature(self.time_signature)
        self.key = canonical_key(self.key)
        self.scale = canonical_scale(self.scale)
        if not 0.0 <= float(self.rest_probability) < 1.0:
            raise ValidationError("rest probability must be 0 <= p < 1")
        lo, hi = self.velocity
        if not 1 <= lo <= hi <= 127:
            raise ValidationError("velocity range must be within 1..127")
        if not self.lengths or any(not 0.015625 <= float(x) <= 16 for x in self.lengths):
            raise ValidationError("note lengths must be 0.015625..16 beats")
        if self.lane_ranges is not None:
            for a, b in self.lane_ranges:
                if not 0 <= a <= b <= 127:
                    raise ValidationError("lane range outside 0..127")
                if not self.pitches((a, b)):
                    raise ValidationError(f"lane range {a}-{b} contains no {self.scale} notes in {self.key}")
        if self.programs is not None and any(not 0 <= int(p) <= 127 for p in self.programs):
            raise ValidationError("GM programs must be 0..127")
        return self

    @property
    def beats_per_bar(self) -> float:
        num, den = parse_time_signature(self.time_signature)
        return num * 4.0 / den

    def role(self, lane: int) -> str:
        return ROLES[lane % len(ROLES)]

    def lane_range(self, lane: int) -> tuple[int, int]:
        if self.lane_ranges:
            return tuple(self.lane_ranges[lane % len(self.lane_ranges)])  # type: ignore[return-value]
        return ROLE_RANGES[self.role(lane)]

    def pitches(self, rng: tuple[int, int]) -> list[int]:
        root = KEYS.index(self.key)
        classes = {(root + i) % 12 for i in SCALES[self.scale]}
        return [n for n in range(rng[0], rng[1] + 1) if n % 12 in classes]

    def program(self, lane: int) -> int | None:
        return None if not self.programs else int(self.programs[lane % len(self.programs)])

    def public(self) -> dict[str, Any]:
        d = asdict(self)
        d["velocity"] = list(self.velocity)
        d["lengths"] = list(self.lengths)
        return d


def midi_channel(lane: int) -> int:
    """Lane -> MIDI channel, skipping channel 10 (index 9, GM percussion)."""
    ch = lane % 15
    return ch if ch < 9 else ch + 1


def bytes_needed(controls: MidiControls, bars: int) -> int:
    total = bars * controls.beats_per_bar
    return 4 * (int(total / min(controls.lengths)) + 2)


def lane_notes(data: bytes, lane: int, bars: int, controls: MidiControls) -> list[dict]:
    """Map entropy bytes to one lane's notes. 4 bytes per event:
    b0 rest decision (b0/256 < rest_probability), b1 scale degree within the lane
    range, b2 velocity within the range, b3 length from the length set.
    Events are monophonic and contiguous; the last one is clipped at the end."""
    pitches = controls.pitches(controls.lane_range(lane))
    vlo, vhi = controls.velocity
    total = round(bars * controls.beats_per_bar * TICKS_PER_BEAT)
    notes, tick = [], 0
    for i in range(0, len(data) - 3, 4):
        if tick >= total:
            break
        b0, b1, b2, b3 = data[i:i + 4]
        length = round(controls.lengths[b3 % len(controls.lengths)] * TICKS_PER_BEAT)
        length = min(length, total - tick)
        if b0 / 256.0 >= controls.rest_probability:
            notes.append({
                "pitch": pitches[b1 % len(pitches)],
                "velocity": vlo + b2 % (vhi - vlo + 1),
                "start_tick": tick,
                "duration_ticks": length,
                "lane": lane,
            })
        tick += length
    if tick < total:
        raise ValidationError("not enough entropy bytes for the requested bars")
    return notes


@dataclass
class VarySpec:
    """Ranges / choice lists for per-piece variation (dataset --vary)."""
    tempo_range: tuple[float, float] | None = None
    scales: list[str] | None = None
    keys: list[str] | None = None
    time_signatures: list[str] | None = None
    rest_range: tuple[float, float] | None = None
    lanes_range: tuple[int, int] | None = None
    bars_range: tuple[int, int] | None = None

    def bytes_needed(self) -> int:
        return 16


def _pick(seq, b: int):
    return seq[b % len(seq)]


def vary_controls(base: MidiControls, spec: VarySpec, data: bytes, lanes: int, bars: int):
    """Choose per-piece values from entropy bytes; returns (controls, lanes, bars, drawn)."""
    if len(data) < 16:
        raise ValidationError("vary needs 16 entropy bytes")
    c = MidiControls(**{**asdict(base)})
    drawn: dict[str, Any] = {}
    if spec.tempo_range:
        lo, hi = spec.tempo_range
        frac = int.from_bytes(data[0:2], "big") / 65535.0
        c.tempo = round(lo + (hi - lo) * frac, 1)
        drawn["tempo"] = c.tempo
    if spec.scales:
        c.scale = canonical_scale(_pick(spec.scales, data[2])); drawn["scale"] = c.scale
    if spec.keys:
        c.key = canonical_key(_pick(spec.keys, data[3])); drawn["key"] = c.key
    if spec.time_signatures:
        c.time_signature = _pick(spec.time_signatures, data[4]); drawn["time_signature"] = c.time_signature
    if spec.rest_range:
        lo, hi = spec.rest_range
        c.rest_probability = round(lo + (hi - lo) * data[5] / 255.0, 3); drawn["rest_probability"] = c.rest_probability
    if spec.lanes_range:
        lo, hi = spec.lanes_range
        lanes = lo + data[6] % (hi - lo + 1); drawn["lanes"] = lanes
    if spec.bars_range:
        lo, hi = spec.bars_range
        bars = lo + data[7] % (hi - lo + 1); drawn["bars"] = bars
    return c.validate(), lanes, bars, drawn


__all__ = [
    "KEYS", "MidiControls", "ROLE_RANGES", "ROLES", "SCALES", "SCALE_ALIASES", "TIME_SIGNATURES",
    "VarySpec", "bytes_needed", "canonical_key", "canonical_scale", "lane_notes", "midi_channel",
    "midi_to_note", "parse_range", "parse_time_signature", "vary_controls",
]
