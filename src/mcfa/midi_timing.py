"""Bar-boundary tempo maps and duration planning; caller supplies all entropy."""
from __future__ import annotations

import math


def tempo_values(start, changes, bounds, max_jump, data):
    import mido
    if not isinstance(changes, int) or not 0 <= changes <= 1024:
        raise ValueError("tempo_changes must be an integer in 0..1024")
    lo, hi = bounds or (start, start)
    if not all(math.isfinite(x) for x in (start, lo, hi)) or not 20 <= lo <= hi <= 400:
        raise ValueError("tempo range must satisfy 20 <= MIN <= MAX <= 400")
    if changes and not lo <= start <= hi:
        raise ValueError("start tempo must lie within the automation range")
    if max_jump is not None and (not math.isfinite(max_jump) or max_jump < 0):
        raise ValueError("tempo max jump must be finite and >= 0")
    if len(data) != changes * 2:
        raise ValueError("tempo automation needs exactly two entropy bytes per change")
    initial = mido.bpm2tempo(start)
    if bounds and lo <= start <= hi:
        initial = max(math.ceil(60_000_000 / hi), min(math.floor(60_000_000 / lo), initial))
    values = [initial]
    if bounds is None or max_jump == 0:
        return values + values * changes
    # MIDI stores integer microseconds, so constrain the encoded tempos themselves.
    for i in range(changes):
        previous = mido.tempo2bpm(values[-1])
        a = max(lo, previous - max_jump) if max_jump is not None else lo
        b = min(hi, previous + max_jump) if max_jump is not None else hi
        slow, fast = math.floor(60_000_000 / a), math.ceil(60_000_000 / b)
        if fast > slow:
            raise ValueError("tempo range/jump contains no representable MIDI tempo")
        fraction = int.from_bytes(data[i * 2:i * 2 + 2], "big") / 65535
        bpm = a + (b - a) * fraction
        values.append(max(fast, min(slow, mido.bpm2tempo(bpm))))
    return values


def tempo_map(bars, values):
    if bars < len(values):
        raise ValueError("bars must exceed the number of tempo changes")
    return [(i * bars // len(values), tempo) for i, tempo in enumerate(values)]


def duration_seconds(bars, beats_per_bar, values):
    plan = tempo_map(bars, values)
    return sum(((plan[i + 1][0] if i + 1 < len(plan) else bars) - bar)
               * beats_per_bar * tempo / 1_000_000 for i, (bar, tempo) in enumerate(plan))


def plan_timing(controls, bars, changes=0, bounds=None, max_jump=None, data=b"", duration=None):
    """Return whole bars and (bar, microseconds/quarter) events, including bar 0.

    Search all feasible whole-bar lengths. If none meets +/-2 seconds, fail
    explicitly rather than stretching notes or moving events off bar boundaries.
    """
    values = tempo_values(controls.tempo, changes, bounds, max_jump, data)
    if duration is not None:
        if not math.isfinite(duration) or duration <= 0:
            raise ValueError("duration must be positive and finite")
        fastest_bar = controls.beats_per_bar * min(values) / 1_000_000
        upper = math.floor((duration + 2) / fastest_bar)
        if upper > 100_000:
            raise ValueError("duration would require too many bars (limit 100000)")
        candidates = range(len(values), upper + 1)
        bars = min(candidates, key=lambda n: abs(duration_seconds(n, controls.beats_per_bar, values) - duration), default=0)
        if not bars or abs(duration_seconds(bars, controls.beats_per_bar, values) - duration) > 2:
            raise ValueError("no whole-bar duration within +/-2 s for these tempo controls")
    return bars, tempo_map(bars, values)
