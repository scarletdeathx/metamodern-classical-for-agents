"""Strict parsing checks for the optional dense/changing MIDI path."""
from __future__ import annotations

from bisect import bisect_right
from collections import defaultdict
import math

from .midi_analysis import analyze_midi
from .midi_controls import KEYS, SCALES, canonical_key
from .midi_motion import MotionControls, MOVING_CCS, STEADY_CCS


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def verify_motion(mid, row, logged=None, fixed=None):
    motion = MotionControls(**row["motion"]).validate()
    a = analyze_midi(mid)
    metrics, duration = a["metrics"], a["duration_s"]
    for name, value in metrics.items():
        _require(name in row and math.isclose(row[name], value, abs_tol=1e-7), f"motion metric mismatch: {name}")
    _require(metrics["notes_per_sec"] + 1e-9 >= motion.min_notes_per_sec, "density below floor")
    _require(motion.max_gap_s is None or metrics["max_gap_s"] <= motion.max_gap_s + 1e-9, "silence exceeds gap limit")
    _require(len(a["endpoints"]) == len(row["lanes"]), "motion lane count")
    _require(len(set(a["endpoints"])) == 1, "motion endpoints differ")
    end, tpb = a["endpoints"][0], mid.ticks_per_beat
    _require(math.isclose(end / tpb, row["bars"] * int(row["time_signature"].split('/')[0]) * 4 / int(row["time_signature"].split('/')[1])), "motion bar endpoint")
    _require(math.isclose(duration, row["duration_s"], abs_tol=1e-6), "motion duration mismatch")
    bounds = (fixed or {}).get("tempo_change_range", (20, 400))
    bpms = [60_000_000 / value for _, value in a["tempos"]]
    _require(all(bounds[0] <= value <= bounds[1] for value in bpms), "motion tempo outside range")
    _require(row["tempo"]["start"] == bpms[0], "motion starting tempo")
    if len(set(bpms)) > 1:
        _require(row["tempo"].get("min") == min(bpms) and row["tempo"].get("max") == max(bpms), "motion tempo extrema")
    if motion.tempo_interval_beats:
        step = round(tpb * motion.tempo_interval_beats)
        _require([tick for tick, _ in a["tempos"]] == list(range(0, end, step)), "tempo change frequency")
        _require(all(x != y for (_, x), (_, y) in zip(a["tempos"], a["tempos"][1:])), "tempo event did not change value")
    keys = a["key_events"]
    if motion.harmony_interval_beats:
        step = round(tpb * motion.harmony_interval_beats)
        _require([tick for tick, _ in keys] == list(range(0, end, step)), "key change frequency")
        roots = [canonical_key(name) for _, name in keys]
        _require(all(k in motion.harmony_keys for k in roots), "key outside eligible choices")
        _require(all(a != b for a, b in zip(roots, roots[1:])), "key did not change")
    programs = defaultdict(list)
    for tick, channel, program in a["program_events"]:
        _require(tick == 0, "mid-piece program change")
        programs[channel].append(program)
    for lane in row["lanes"]:
        expected = [lane["program"]] if lane["program"] is not None else []
        _require(programs[lane["channel"]] == expected, "program inventory mismatch")
    _require(not set(a["cc_counts"]) & set(STEADY_CCS), "steady controls touched")
    cc_by_channel, bends_by_channel = defaultdict(list), defaultdict(list)
    for tick, channel, cc, value in a["cc_events"]:
        _require(cc in MOVING_CCS and 0 <= value <= 127, "unexpected/out of range CC")
        cc_by_channel[channel, cc].append((tick, value))
    for tick, channel, value in a["bend_events"]:
        _require(-8192 <= value <= 8191, "pitch bend outside range")
        bends_by_channel[channel].append((tick, value))
    for lane in row["lanes"]:
        channel = lane["channel"]
        for cc in MOVING_CCS:
            seq = cc_by_channel[channel, cc]
            expected_ticks = list(range(0, end, round(tpb*motion.cc_interval_beats))) if motion.cc_interval_beats else []
            _require([tick for tick, _ in seq] == expected_ticks, f"CC{cc} frequency")
            _require(all(x != y for (_, x), (_, y) in zip(seq, seq[1:])), f"CC{cc} repeated value")
        seq = bends_by_channel[channel]
        expected_ticks = list(range(0, end, round(tpb*motion.pitch_bend_interval_beats))) if motion.pitch_bend_interval_beats else []
        _require([tick for tick, _ in seq] == expected_ticks, "pitch bend frequency")
        _require(all(x != y for (_, x), (_, y) in zip(seq, seq[1:])), "pitch bend repeated value")
    # Meta events and note pairings are checked independently from generator code.
    for lane_index, track in enumerate(mid.tracks):
        signatures, tick = [], 0
        for msg in track:
            tick += msg.time
            if msg.type == "time_signature":
                signatures.append(f"{msg.numerator}/{msg.denominator}")
            if msg.type in ("set_tempo", "key_signature"):
                _require(lane_index == 0, "motion conductor metadata in another lane")
            if msg.type == "track_name":
                _require(msg.name == f"lane {lane_index}", "non-neutral track name")
            _require(msg.type not in ("text", "marker", "lyrics", "instrument_name", "copyright", "sequencer_specific"), "unexpected text/opaque metadata")
        _require(signatures == ([row["time_signature"]] if lane_index == 0 else []), "motion meter mismatch")
    harmonic_count = 0
    if motion.harmony_interval_beats and logged:
        harmony = logged["params"]["harmony"]
        _require([(e["tick"], e["key"]) for e in harmony] == [(tick, canonical_key(key)) for tick, key in keys], "harmony/key metadata mismatch")
        for i, event in enumerate(harmony):
            _require(event["scale"] in motion.harmony_scales, "harmony scale outside choices")
            scale_classes = {(KEYS.index(event["key"]) + n) % 12 for n in SCALES[event["scale"]]}
            _require(set(event["chord"]) <= scale_classes, "chord outside scale")
            _require(len(event["chord"]) in motion.chord_sizes, "chord size outside choices")
            if i:
                _require(event["chord"] != harmony[i-1]["chord"], "chord did not change")
        hticks = [e["tick"] for e in harmony]
        sounded = defaultdict(set)
        for start, stop, lane_index, pitch, _ in a["notes"]:
            event = harmony[bisect_right(hticks, start)-1]
            _require(pitch % 12 in event["chord"], "note outside active chord")
            sounded[event["tick"]].add(pitch % 12)
        _require(all(sounded[e["tick"]] == set(e["chord"]) for e in harmony), "chord never sounded")
        harmonic_count = len(harmony) - 1
    _require(len(a["notes"]) == row["note_count"], "motion note count")
    for _, _, lane_index, pitch, channel in a["notes"]:
        lane = row["lanes"][lane_index]
        lo, hi = lane["range"]
        _require(channel == lane["channel"] and lo <= pitch <= hi, "motion note outside lane range/channel")
    if logged:
        _require(logged["sha256"] == row["sha256"], "motion provenance hash mismatch")
        _require(a["tempos"] == [tuple(e) for e in logged["params"]["tempo_map_ticks"]], "motion tempo map mismatch")
        lo, hi = logged["params"]["controls"]["velocity"]
        _require(all(lo <= v <= hi for v in a["velocity_values"]), "motion velocity range")
        _require(len(a["velocity_values"]) > 1 or lo == hi, "motion velocity never varied")
    return {"metrics": metrics, "duration_s": duration, "max_onset_gap_s": a["max_onset_gap_s"], "tempo_bpms": bpms,
            "harmony_change_count": harmonic_count, "key_change_count": max(0, len(keys)-1),
            "cc_counts": a["cc_counts"], "velocity_distinct": len(a["velocity_values"]),
            "keys": sorted({canonical_key(k) for _, k in keys}),
            "scales": sorted({e["scale"] for e in logged["params"]["harmony"]}) if logged and motion.harmony_interval_beats else []}
