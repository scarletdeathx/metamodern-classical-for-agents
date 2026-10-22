"""File-only measurements in seconds, integrating the encoded MIDI tempo map."""
from __future__ import annotations

from bisect import bisect_right
from collections import Counter


class MidiClock:
    def __init__(self, events, ticks_per_beat=480):
        self.tpb = ticks_per_beat
        self.events = sorted(events)
        if not self.events or self.events[0][0] != 0:
            self.events.insert(0, (0, 500000))
        self.ticks, self.seconds, self.tempos = [], [], []
        last, elapsed, tempo = 0, 0.0, 500000
        for tick, value in self.events:
            elapsed += (tick - last) * tempo / ticks_per_beat / 1_000_000
            self.ticks.append(tick)
            self.seconds.append(elapsed)
            self.tempos.append(value)
            last, tempo = tick, value

    def seconds_at(self, tick):
        i = bisect_right(self.ticks, tick) - 1
        return self.seconds[i] + (tick - self.ticks[i]) * self.tempos[i] / self.tpb / 1_000_000

    def tick_at(self, seconds):
        i = bisect_right(self.seconds, seconds) - 1
        return self.ticks[i] + (seconds - self.seconds[i]) * self.tpb * 1_000_000 / self.tempos[i]


def analyze_midi(mid):
    """Silence is the union of sounding notes, including leading/trailing silence.

    Distinct channels/pitches are paired; overlapping equal notes are rejected
    so a misleading note count cannot disguise broken polyphony.
    """
    tempos, endpoints, notes, ccs, bends, keys = [], [], [], [], [], []
    programs, controls, velocities = [], Counter(), set()
    for lane, track in enumerate(mid.tracks):
        tick, active = 0, {}
        for msg in track:
            tick += msg.time
            if msg.type == "set_tempo":
                tempos.append((tick, msg.tempo))
            elif msg.type == "key_signature":
                keys.append((tick, msg.key))
            elif msg.type == "program_change":
                programs.append((tick, msg.channel, msg.program))
            elif msg.type == "control_change":
                ccs.append((tick, msg.channel, msg.control, msg.value))
                controls[msg.control] += 1
            elif msg.type == "pitchwheel":
                bends.append((tick, msg.channel, msg.pitch))
            elif msg.type == "note_on" and msg.velocity:
                k = (msg.channel, msg.note)
                if k in active:
                    raise ValueError("overlapping equal notes on one channel")
                active[k] = tick
                velocities.add(msg.velocity)
            elif msg.type == "note_off" or msg.type == "note_on" and not msg.velocity:
                start = active.pop((msg.channel, msg.note), None)
                if start is None or tick <= start:
                    raise ValueError("unmatched/nonpositive MIDI note")
                notes.append((start, tick, lane, msg.note, msg.channel))
        if active:
            raise ValueError("hanging MIDI notes")
        endpoints.append(tick)
    clock = MidiClock(tempos, mid.ticks_per_beat)
    duration = clock.seconds_at(max(endpoints, default=0))
    if duration <= 0:
        raise ValueError("nonpositive MIDI duration")
    end, max_gap = 0, 0.0
    for start, stop, *_ in sorted(notes):
        if start > end:
            max_gap = max(max_gap, clock.seconds_at(start) - clock.seconds_at(end))
        end = max(end, stop)
    max_gap = max(max_gap, duration - clock.seconds_at(end))
    onset_ticks = sorted({0, max(endpoints, default=0)} | {start for start, *_ in notes})
    max_onset_gap = max((clock.seconds_at(b) - clock.seconds_at(a) for a, b in zip(onset_ticks, onset_ticks[1:])), default=duration)
    metrics = {"notes_per_sec": len(notes) / duration, "max_gap_s": max_gap,
               "tempo_change_count": sum(tick > 0 for tick, _ in tempos),
               "cc_events_per_sec": len(ccs) / duration,
               "pitch_bend_events_per_sec": len(bends) / duration}
    return {"metrics": metrics, "clock": clock, "max_onset_gap_s": max_onset_gap, "duration_s": duration, "notes": notes,
            "tempos": sorted(tempos), "key_events": sorted(keys), "cc_events": ccs,
            "bend_events": bends, "cc_counts": dict(controls), "program_events": programs,
            "endpoints": endpoints, "velocity_values": velocities}


METRIC_FIELDS = {"notes_per_sec", "max_gap_s", "tempo_change_count", "cc_events_per_sec", "pitch_bend_events_per_sec"}
