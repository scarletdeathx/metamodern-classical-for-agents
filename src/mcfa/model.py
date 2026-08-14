"""State model, note parsing, and validation shared by CLI and engine."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import math
import re
from typing import Any, Iterable


MAX_CHANNELS = 10
MAX_RANDOM_SEED = (1 << 128) - 1
WAVEFORMS = {"sine", "triangle", "saw", "square", "noise"}
FILTER_TYPES = {"off", "lowpass", "highpass", "bandpass"}
CLOCK_MODES = {"free", "sync"}
MODULATION_TARGETS = {"off", "amplitude", "pan", "cutoff"}
MODULATION_WAVEFORMS = {"sine", "triangle", "square"}
QUANTIZATIONS = {"now", "next-step", "next-beat", "next-bar"}

_NOTE_RE = re.compile(r"^([A-Ga-g])([#b]?)(-?\d)$")
_PITCH_CLASS = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}


class ValidationError(ValueError):
    """An invalid musical or command value."""


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def note_to_midi(value: str | int | float) -> int:
    """Convert a note name such as C#3 or a MIDI number into 0..127."""
    if isinstance(value, bool):
        raise ValidationError("a Boolean is not a MIDI note")
    if isinstance(value, (int, float)):
        midi = int(value)
        if float(value) != midi:
            raise ValidationError(f"MIDI note must be an integer: {value!r}")
    else:
        text = str(value).strip()
        if text.lstrip("-").isdigit():
            midi = int(text)
        else:
            match = _NOTE_RE.match(text)
            if not match:
                raise ValidationError(f"invalid note {value!r}; use names like C3, F#4, Bb2")
            letter, accidental, octave_text = match.groups()
            pitch = _PITCH_CLASS[letter.upper()]
            if accidental == "#":
                pitch += 1
            elif accidental == "b":
                pitch -= 1
            midi = (int(octave_text) + 1) * 12 + pitch
    if not 0 <= midi <= 127:
        raise ValidationError(f"MIDI note is outside 0..127: {midi}")
    return midi


def midi_to_note(midi: int) -> str:
    names = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")
    midi = int(midi)
    return f"{names[midi % 12]}{midi // 12 - 1}"


def midi_frequency(midi: int) -> float:
    return 440.0 * (2.0 ** ((midi - 69) / 12.0))


@dataclass
class Step:
    notes: list[int] = field(default_factory=list)
    velocity: float = 0.8
    gate: float = 0.8
    probability: float = 1.0

    def validate(self) -> None:
        self.notes = [note_to_midi(note) for note in self.notes]
        self.velocity = _bounded("velocity", self.velocity, 0.0, 1.0)
        self.gate = _bounded("gate", self.gate, 0.01, 4.0)
        self.probability = _bounded("probability", self.probability, 0.0, 1.0)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Step":
        notes = data.get("notes", [])
        if isinstance(notes, (str, int, float)):
            notes = [notes]
        step = cls(
            notes=list(notes),
            velocity=data.get("velocity", 0.8),
            gate=data.get("gate", 0.8),
            probability=data.get("probability", 1.0),
        )
        step.validate()
        return step

    def public(self) -> dict[str, Any]:
        return {
            "notes": [midi_to_note(note) for note in self.notes],
            "midi": list(self.notes),
            "velocity": self.velocity,
            "gate": self.gate,
            "probability": self.probability,
        }


def parse_pattern(text: str) -> list[Step]:
    """Parse whitespace/comma-separated steps.

    Syntax: ``C3`` for a note, ``C3+E3+G3`` for a chord, and ``.`` for a rest.
    A note/chord may append ``:velocity:gate:probability``. Omitted modifiers keep
    their defaults; for example ``C3:0.6:0.25``.
    """
    tokens = [token for token in re.split(r"[\s,]+", text.strip()) if token]
    if not tokens:
        raise ValidationError("pattern cannot be empty")
    result: list[Step] = []
    for token in tokens:
        parts = token.split(":")
        pitch_text = parts[0]
        if len(parts) > 4:
            raise ValidationError(f"too many modifiers in pattern step {token!r}")
        if pitch_text in {".", "-", "_", "r", "R"}:
            if len(parts) > 1:
                raise ValidationError(f"rest step cannot have modifiers: {token!r}")
            result.append(Step())
            continue
        notes = [note_to_midi(note) for note in pitch_text.split("+")]
        values = [0.8, 0.8, 1.0]
        for index, modifier in enumerate(parts[1:]):
            if modifier:
                try:
                    values[index] = float(modifier)
                except ValueError as exc:
                    raise ValidationError(f"invalid step modifier in {token!r}") from exc
        step = Step(notes, values[0], values[1], values[2])
        step.validate()
        result.append(step)
    return result


def pattern_from_json(values: Iterable[Any]) -> list[Step]:
    result: list[Step] = []
    for value in values:
        if value is None or (isinstance(value, str) and value in {".", "-"}):
            result.append(Step())
        elif isinstance(value, dict):
            result.append(Step.from_dict(value))
        elif isinstance(value, (str, int, float)):
            result.append(Step([note_to_midi(value)]))
        elif isinstance(value, list):
            result.append(Step([note_to_midi(note) for note in value]))
        else:
            raise ValidationError(f"invalid JSON pattern step: {value!r}")
    if not result:
        raise ValidationError("pattern cannot be empty")
    return result


@dataclass
class Envelope:
    attack: float = 0.005
    decay: float = 0.08
    sustain: float = 0.65
    release: float = 0.15

    def update(self, patch: dict[str, Any]) -> None:
        for key in ("attack", "decay", "sustain", "release"):
            if key in patch:
                setattr(self, key, float(patch[key]))
        self.attack = _bounded("attack", self.attack, 0.0001, 10.0)
        self.decay = _bounded("decay", self.decay, 0.0, 10.0)
        self.sustain = _bounded("sustain", self.sustain, 0.0, 1.0)
        self.release = _bounded("release", self.release, 0.001, 20.0)


@dataclass
class Filter:
    type: str = "lowpass"
    cutoff: float = 8000.0
    resonance: float = 0.1

    def update(self, patch: dict[str, Any]) -> None:
        if "type" in patch:
            self.type = str(patch["type"])
        if self.type not in FILTER_TYPES:
            raise ValidationError(f"filter type must be one of {sorted(FILTER_TYPES)}")
        if "cutoff" in patch:
            self.cutoff = float(patch["cutoff"])
        if "resonance" in patch:
            self.resonance = float(patch["resonance"])
        self.cutoff = _bounded("cutoff", self.cutoff, 20.0, 20000.0)
        self.resonance = _bounded("resonance", self.resonance, 0.0, 0.95)


@dataclass
class Effects:
    drive: float = 0.0
    delay_mix: float = 0.0
    delay_time: float = 0.25
    delay_feedback: float = 0.25
    reverb_mix: float = 0.0

    def update(self, patch: dict[str, Any]) -> None:
        for key in ("drive", "delay_mix", "delay_time", "delay_feedback", "reverb_mix"):
            if key in patch:
                setattr(self, key, float(patch[key]))
        self.drive = _bounded("drive", self.drive, 0.0, 1.0)
        self.delay_mix = _bounded("delay_mix", self.delay_mix, 0.0, 1.0)
        self.delay_time = _bounded("delay_time", self.delay_time, 0.01, 2.0)
        self.delay_feedback = _bounded("delay_feedback", self.delay_feedback, 0.0, 0.95)
        self.reverb_mix = _bounded("reverb_mix", self.reverb_mix, 0.0, 1.0)


@dataclass
class Modulation:
    """A deliberately small per-lane LFO for continuously moving noise."""

    target: str = "off"
    waveform: str = "sine"
    rate_hz: float = 0.25
    depth: float = 0.0

    def update(self, patch: dict[str, Any]) -> None:
        if "target" in patch:
            self.target = str(patch["target"])
        if self.target not in MODULATION_TARGETS:
            raise ValidationError(f"modulation target must be one of {sorted(MODULATION_TARGETS)}")
        if "waveform" in patch:
            self.waveform = str(patch["waveform"])
        if self.waveform not in MODULATION_WAVEFORMS:
            raise ValidationError(f"modulation waveform must be one of {sorted(MODULATION_WAVEFORMS)}")
        if "rate_hz" in patch:
            self.rate_hz = float(patch["rate_hz"])
        if "depth" in patch:
            self.depth = float(patch["depth"])
        self.rate_hz = _bounded("modulation rate_hz", self.rate_hz, 0.01, 40.0)
        self.depth = _bounded("modulation depth", self.depth, 0.0, 1.0)


@dataclass
class Synth:
    waveform: str = "sine"
    detune: float = 0.0
    envelope: Envelope = field(default_factory=Envelope)
    filter: Filter = field(default_factory=Filter)
    effects: Effects = field(default_factory=Effects)
    modulation: Modulation = field(default_factory=Modulation)

    def update(self, patch: dict[str, Any]) -> None:
        if "waveform" in patch:
            self.waveform = str(patch["waveform"])
        if self.waveform not in WAVEFORMS:
            raise ValidationError(f"waveform must be one of {sorted(WAVEFORMS)}")
        if "detune" in patch:
            self.detune = float(patch["detune"])
        self.detune = _bounded("detune", self.detune, -100.0, 100.0)
        if "envelope" in patch:
            self.envelope.update(dict(patch["envelope"]))
        if "filter" in patch:
            self.filter.update(dict(patch["filter"]))
        if "effects" in patch:
            self.effects.update(dict(patch["effects"]))
        if "modulation" in patch:
            self.modulation.update(dict(patch["modulation"]))


@dataclass
class Channel:
    id: int
    name: str = ""
    active: bool = True
    muted: bool = False
    clock: str = "free"
    bpm: float = 120.0
    volume: float = 0.65
    pan: float = 0.0
    step_beats: float = 0.25
    random_seed: int | None = None
    pattern: list[Step] = field(default_factory=list)
    synth: Synth = field(default_factory=Synth)

    def update(self, patch: dict[str, Any]) -> None:
        allowed = {
            "name",
            "active",
            "muted",
            "clock",
            "bpm",
            "volume",
            "pan",
            "step_beats",
            "random_seed",
            "pattern",
            "synth",
        }
        unknown = set(patch) - allowed
        if unknown:
            raise ValidationError(f"unknown channel fields: {', '.join(sorted(unknown))}")
        if "name" in patch:
            self.name = str(patch["name"])[:40]
        if "active" in patch:
            self.active = bool(patch["active"])
        if "muted" in patch:
            self.muted = bool(patch["muted"])
        if "clock" in patch:
            self.clock = str(patch["clock"])
        if self.clock not in CLOCK_MODES:
            raise ValidationError(f"clock must be one of {sorted(CLOCK_MODES)}")
        if "bpm" in patch:
            self.bpm = validate_bpm(patch["bpm"])
        if "volume" in patch:
            self.volume = _bounded("volume", patch["volume"], 0.0, 1.0)
        if "pan" in patch:
            self.pan = _bounded("pan", patch["pan"], -1.0, 1.0)
        if "step_beats" in patch:
            self.step_beats = _bounded("step_beats", patch["step_beats"], 1 / 64, 16.0)
        if "random_seed" in patch:
            self.random_seed = validate_random_seed(patch["random_seed"])
        if "pattern" in patch:
            raw_pattern = patch["pattern"]
            if not isinstance(raw_pattern, list):
                raise ValidationError("pattern must be a JSON list")
            self.pattern = pattern_from_json(raw_pattern) if raw_pattern else []
            if len(self.pattern) > 256:
                raise ValidationError("pattern cannot exceed 256 steps")
        if "synth" in patch:
            self.synth.update(dict(patch["synth"]))

    def public(self) -> dict[str, Any]:
        data = asdict(self)
        data["random_seed"] = random_seed_public(self.random_seed)
        data["pattern"] = [step.public() for step in self.pattern]
        data["loop_steps"] = len(self.pattern)
        data["loop_beats"] = round(len(self.pattern) * self.step_beats, 6)
        data["loop_seconds"] = round(len(self.pattern) * self.step_beats * 60.0 / self.bpm, 6)
        return data


def default_channels(bpm: float = 120.0) -> list[Channel]:
    lane_bpm = validate_bpm(bpm)
    return [Channel(id=index, bpm=lane_bpm) for index in range(1, MAX_CHANNELS + 1)]


def validate_channel_id(value: Any) -> int:
    try:
        channel = int(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"channel must be 1..{MAX_CHANNELS}") from exc
    if not 1 <= channel <= MAX_CHANNELS:
        raise ValidationError(f"channel must be 1..{MAX_CHANNELS}")
    return channel


def validate_bpm(value: Any) -> float:
    return _bounded("bpm", value, 20.0, 400.0)


def validate_random_seed(value: Any) -> int | None:
    """Validate an already-resolved lane RNG seed.

    The engine resolves the user-facing ``"system"`` sentinel before a patch
    reaches the model. ``None`` or ``"default"`` restores MCFA's stable
    lane-derived seed.
    """
    if value is None or (isinstance(value, str) and value.strip().lower() == "default"):
        return None
    if isinstance(value, bool):
        raise ValidationError("random_seed must be an integer, 'system', or 'default'")
    try:
        if isinstance(value, str) and value.strip().lower().startswith("0x"):
            seed = int(value.strip(), 16)
        else:
            seed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError("random_seed must be an integer, 'system', or 'default'") from exc
    if isinstance(value, float) and value != seed:
        raise ValidationError("random_seed must be an integer, 'system', or 'default'")
    if isinstance(value, str) and not value.strip().lower().startswith("0x") and value.strip() != str(seed):
        raise ValidationError("random_seed must be an integer, 'system', or 'default'")
    if not 0 <= seed <= MAX_RANDOM_SEED:
        raise ValidationError(f"random_seed must be between 0 and {MAX_RANDOM_SEED}")
    return seed


def random_seed_public(value: int | None) -> str | None:
    """Return an exact JSON-safe representation of a lane seed."""
    return None if value is None else f"0x{value:032x}"


def validate_at(value: str) -> str:
    if value in QUANTIZATIONS:
        return value
    if re.match(r"^\+(?:\d+(?:\.\d+)?|\.\d+)(?:beats?)?$", value):
        return value
    raise ValidationError("--at must be now, next-step, next-beat, next-bar, or +Nbeats")


def _bounded(name: str, value: Any, low: float, high: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"{name} must be a number") from exc
    if not math.isfinite(number) or not low <= number <= high:
        raise ValidationError(f"{name} must be between {low:g} and {high:g}")
    return number
