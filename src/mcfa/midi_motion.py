"""Dense, changing MIDI controls. Every creative choice consumes supplied entropy.

No PRNG and no entropy fallback. Tempo/harmony use beat intervals; density and
silence contracts use seconds integrated from the actual encoded tempo map.
"""
from __future__ import annotations

from bisect import bisect_right
from dataclasses import asdict, dataclass
import hashlib
import math

from .midi_analysis import MidiClock, analyze_midi
from .midi_controls import KEYS, SCALES, MidiControls, canonical_key, canonical_scale, midi_channel

MOVING_CCS = (1, 91, 93)
STEADY_CCS = (7, 11, 10, 64, 71, 74)
# mido accepts standard spellings in key_signature messages.
MIDI_KEYS = ("C", "Db", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B")


@dataclass
class MotionControls:
    min_notes_per_sec: float = 0.0
    max_gap_s: float | None = None
    note_step_beats: float = 0.125
    tempo_interval_beats: float | None = None
    harmony_interval_beats: float | None = None
    cc_interval_beats: float | None = None
    pitch_bend_interval_beats: float | None = None
    harmony_keys: list[str] | str = "all"
    harmony_scales: list[str] | str = "all"
    chord_sizes: tuple[int, ...] = (2, 3, 4)

    def validate(self):
        if not math.isfinite(self.min_notes_per_sec) or not 0 <= self.min_notes_per_sec <= 1000:
            raise ValueError("min_notes_per_sec must be finite and in 0..1000")
        if self.max_gap_s is not None and (not math.isfinite(self.max_gap_s) or not 0 <= self.max_gap_s <= 60):
            raise ValueError("max_gap_s must be finite and in 0..60")
        for name in ("note_step_beats", "tempo_interval_beats", "harmony_interval_beats",
                     "cc_interval_beats", "pitch_bend_interval_beats"):
            value = getattr(self, name)
            if value is not None and (not math.isfinite(value) or not 1 / 32 <= value <= 16 or not math.isclose(value * 480, round(value * 480))):
                raise ValueError(f"{name} must be 1/32..16 beats on the 480 PPQ grid")
        if not self.note_step_beats:
            raise ValueError("note_step_beats is required")
        self.harmony_keys = list(KEYS) if self.harmony_keys == "all" else [canonical_key(k) for k in self.harmony_keys]
        self.harmony_scales = list(SCALES) if self.harmony_scales == "all" else [canonical_scale(s) for s in self.harmony_scales]
        if not self.harmony_keys or not self.harmony_scales or len(set(self.harmony_keys)) != len(self.harmony_keys):
            raise ValueError("harmony key/scale choices must be nonempty, keys unique")
        if self.harmony_interval_beats and len(self.harmony_keys) < 2:
            raise ValueError("changing harmony needs at least two keys")
        if not self.chord_sizes or any(type(n) is not int or not 1 <= n <= 4 for n in self.chord_sizes):
            raise ValueError("chord_sizes must contain integers in 1..4")
        return self

    def public(self):
        return asdict(self)


def _capture(draw, n, lane):
    data, entry = draw(n, lane)
    if len(data) != n:
        from .providers.base import EntropyProviderError
        raise EntropyProviderError(f"short entropy draw: {len(data)} bytes, expected {n}")
    return data, {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(), **entry}


def _interval_ticks(beats):
    return round(beats * 480) if beats is not None else None


def _different(choices, byte, previous):
    if isinstance(choices, range) and choices.start == 0 and choices.step == 1:
        value = byte % (len(choices) - (previous is not None))
        return value + 1 if previous is not None and value >= previous else value
    allowed = [x for x in choices if x != previous]
    return allowed[byte % len(allowed)] if allowed else previous


def _timing(controls, bars, duration, motion, bounds, draw):
    import mido
    from .midi_timing import plan_timing
    step = _interval_ticks(motion.tempo_interval_beats)
    if step is None:
        bars, plan = plan_timing(controls, bars, duration=duration)
        return bars, round(bars * controls.beats_per_bar * 480), [(0, plan[0][1])], None
    lo, hi = bounds or (20, 400)
    if not all(math.isfinite(x) for x in (lo, hi)) or not 20 <= lo < hi <= 400:
        raise ValueError("frequent tempo changes need a nonzero range within 20..400 BPM")
    if not lo <= controls.tempo <= hi:
        raise ValueError("start tempo must lie within frequent tempo range")
    bar_ticks = round(controls.beats_per_bar * 480)
    if duration is not None:
        if not math.isfinite(duration) or not 0 < duration <= 3600:
            raise ValueError("motion duration must be positive and <= 3600 s")
        upper_bars = max(1, math.floor((duration + 2) * hi / 60 / controls.beats_per_bar))
    else:
        upper_bars = bars
    upper_tick = upper_bars * bar_ticks
    count = (upper_tick - 1) // step
    if count > 500_000:
        raise ValueError("too many tempo events")
    data, provenance = _capture(draw, max(2, count * 2), -2)
    fast, slow = math.ceil(60_000_000 / hi), math.floor(60_000_000 / lo)
    start = max(fast, min(slow, mido.bpm2tempo(controls.tempo)))
    events = [(0, start)]
    for i in range(count):
        fraction = int.from_bytes(data[i*2:i*2+2], "big") / 65535
        tempo = max(fast, min(slow, mido.bpm2tempo(lo + (hi-lo) * fraction)))
        if tempo == events[-1][1]:
            tempo = tempo + 1 if tempo < slow else tempo - 1
        events.append(((i+1)*step, tempo))
    clock = MidiClock(events)
    if duration is not None:
        bars = min(range(1, upper_bars + 1), key=lambda b: abs(clock.seconds_at(b*bar_ticks) - duration))
        if abs(clock.seconds_at(bars*bar_ticks) - duration) > 2:
            raise ValueError("no whole-bar duration within +/-2 s for frequent tempo map")
    end = bars * bar_ticks
    return bars, end, [e for e in events if e[0] < end], provenance


def _harmony(controls, end, motion, draw):
    step = _interval_ticks(motion.harmony_interval_beats)
    if step is None:
        return [], None
    count = (end - 1) // step + 1
    data, provenance = _capture(draw, count * 5, -3)
    events, previous_key, previous_chord = [], None, None
    for i, tick in enumerate(range(0, end, step)):
        a, b, c, d, e = data[i*5:i*5+5]
        key = _different(motion.harmony_keys, a, previous_key)
        scale = motion.harmony_scales[b % len(motion.harmony_scales)]
        intervals = SCALES[scale]
        size = motion.chord_sizes[d % len(motion.chord_sizes)]
        root, stride = c % len(intervals), 1 + e % (len(intervals) - 1)
        degree_order = list(dict.fromkeys((root + j*stride) % len(intervals) for j in range(len(intervals))))
        degree_order += [j for j in range(len(intervals)) if j not in degree_order]
        chord = sorted((KEYS.index(key) + intervals[j]) % 12 for j in degree_order[:size])
        # A new key can share a pitch-class set. Select a different valid voicing
        # when that happens, so harmony changes are actual note changes.
        if chord == previous_chord:
            for j in range(len(intervals)):
                candidate = sorted((KEYS.index(key) + intervals[(j+k) % len(intervals)]) % 12 for k in range(size))
                if candidate != previous_chord:
                    chord = candidate
                    break
        events.append({"tick": tick, "key": key, "scale": scale, "chord": chord})
        previous_key, previous_chord = key, chord
    return events, provenance


def enforce_contract(mid, motion):
    facts = analyze_midi(mid)
    if facts["metrics"]["notes_per_sec"] + 1e-9 < motion.min_notes_per_sec:
        raise ValueError("density below min_notes_per_sec")
    if motion.max_gap_s is not None and facts["metrics"]["max_gap_s"] > motion.max_gap_s + 1e-9:
        raise ValueError("silence exceeds max_gap_s")
    if any(c in facts["cc_counts"] for c in STEADY_CCS):
        raise ValueError("steady CC was automated")
    if any(tick != 0 for tick, _, _ in facts["program_events"]):
        raise ValueError("mid-piece program change")
    return facts


def generate_motion_midi(lanes, bars, controls, motion, draw, *, duration=None, tempo_range=None):
    import mido
    motion = MotionControls(**motion).validate() if isinstance(motion, dict) else motion.validate()
    if not 1 <= lanes <= 15:
        raise ValueError("motion lanes must be 1..15 (unique non-percussion channels)")
    if motion.harmony_interval_beats and any(controls.lane_range(i)[1] - controls.lane_range(i)[0] < 11 for i in range(lanes)):
        raise ValueError("changing chords require lane ranges spanning at least one octave")
    bars, end, tempos, tempo_provenance = _timing(controls, bars, duration, motion, tempo_range, draw)
    harmony, harmony_provenance = _harmony(controls, end, motion, draw)
    harmony_ticks = [e["tick"] for e in harmony]
    clock = MidiClock(tempos)
    pulse_ticks, tick = [], 0
    max_seconds = min(motion.chord_sizes) / motion.min_notes_per_sec if motion.min_notes_per_sec else math.inf
    # Nonzero rest probability is permitted, but lane 0 anchors the guarantees.
    if motion.max_gap_s is not None and motion.max_gap_s > 0:
        max_seconds = min(max_seconds, motion.max_gap_s)
    while tick < end:
        limit = min(end, tick + _interval_ticks(motion.note_step_beats))
        if math.isfinite(max_seconds):
            limit = min(limit, math.floor(clock.tick_at(clock.seconds_at(tick) + max_seconds)))
        if harmony:
            next_harmony = bisect_right(harmony_ticks, tick)
            if next_harmony < len(harmony_ticks):
                limit = min(limit, harmony_ticks[next_harmony])
        if limit <= tick:
            raise ValueError("density target cannot be represented at 480 PPQ")
        pulse_ticks.append((tick, limit))
        tick = limit
    mid = mido.MidiFile(ticks_per_beat=480)
    provenance = {"draws": [], "lane_layout": [], "tempo_map_ticks": tempos,
                  "harmony": harmony, "tempo_draw": tempo_provenance, "harmony_draw": harmony_provenance,
                  "motion": motion.public(), "bars": bars}
    for lane in range(lanes):
        channel, program = midi_channel(lane), controls.program(lane)
        cc_ticks = list(range(0, end, _interval_ticks(motion.cc_interval_beats))) if motion.cc_interval_beats else []
        bend_ticks = list(range(0, end, _interval_ticks(motion.pitch_bend_interval_beats))) if motion.pitch_bend_interval_beats else []
        width = 2 + 2*max(motion.chord_sizes)
        count = len(pulse_ticks)*width + len(cc_ticks)*3 + len(bend_ticks)*2
        data, info = _capture(draw, count, lane)
        provenance["draws"].append({"lane": lane, **info})
        cursor, events = 0, []
        events.append((0, -4, mido.MetaMessage("track_name", name=f"lane {lane}")))
        if lane == 0:
            num, den = map(int, controls.time_signature.split("/"))
            events.append((0, -4, mido.MetaMessage("time_signature", numerator=num, denominator=den)))
            events.extend((t, -3, mido.MetaMessage("set_tempo", tempo=v)) for t, v in tempos)
            events.extend((e["tick"], -2, mido.MetaMessage("key_signature", key=MIDI_KEYS[KEYS.index(e["key"])])) for e in harmony)
        if program is not None:
            events.append((0, -4, mido.Message("program_change", channel=channel, program=program)))
        lo, hi = controls.lane_range(lane)
        note_count = 0
        pitch_choices = {pc: [n for n in range(lo, hi+1) if n % 12 == pc] for pc in range(12)}
        for start, stop in pulse_ticks:
            chunk = data[cursor:cursor+width]
            cursor += width
            if lane and chunk[0] / 256 < controls.rest_probability:
                continue
            h = harmony[bisect_right(harmony_ticks, start)-1] if harmony else None
            classes = h["chord"] if h else sorted({n % 12 for n in controls.pitches((lo, hi))})
            if not h:
                classes = classes[:motion.chord_sizes[chunk[0] % len(motion.chord_sizes)]]
            for j, pitch_class in enumerate(classes):
                choices = pitch_choices[pitch_class]
                pitch = choices[chunk[2+2*j] % len(choices)]
                vlo, vhi = controls.velocity
                velocity = vlo + chunk[3+2*j] % (vhi-vlo+1)
                gate = stop if lane == 0 else max(start+1, start + round((stop-start)*(0.25+0.75*chunk[1]/255)))
                events.append((start, 1, mido.Message("note_on", channel=channel, note=pitch, velocity=velocity)))
                events.append((gate, 0, mido.Message("note_off", channel=channel, note=pitch, velocity=0)))
                note_count += 1
        previous = {cc: None for cc in MOVING_CCS}
        for tick in cc_ticks:
            for cc in MOVING_CCS:
                value = _different(range(128), data[cursor], previous[cc])
                cursor += 1
                previous[cc] = value
                events.append((tick, -1, mido.Message("control_change", channel=channel, control=cc, value=value)))
        previous = None
        for tick in bend_ticks:
            value = int.from_bytes(data[cursor:cursor+2], "big") % 16384 - 8192
            cursor += 2
            if value == previous:
                value = value + 1 if value < 8191 else -8192
            previous = value
            events.append((tick, -1, mido.Message("pitchwheel", channel=channel, pitch=value)))
        track, last = mido.MidiTrack(), 0
        for tick, _, msg in sorted(events, key=lambda e: (e[0], e[1])):
            track.append(msg.copy(time=tick-last))
            last = tick
        track.append(mido.MetaMessage("end_of_track", time=end-last))
        mid.tracks.append(track)
        provenance["lane_layout"].append({"lane": lane, "role": controls.role(lane), "range": [lo, hi],
                                           "channel": channel, "program": program, "notes": note_count})
    enforce_contract(mid, motion)
    return mid, provenance
