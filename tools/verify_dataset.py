#!/usr/bin/env python3
"""Verify a dataset by parsing every MIDI, without opening any audio device."""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import io
import json
import math
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from mcfa.dataset import MANIFEST_FIELDS, midi_path
from mcfa.midi_controls import KEYS, SCALES
from mcfa.recipes import load_recipes


def require(condition, message):
    if not condition:
        raise ValueError(message)


def verify_dataset(out, recipes=None, log=None):
    import mido
    out = Path(out)
    recipe_list = load_recipes(recipes) if recipes else []
    rows = [json.loads(line) for line in (out / "manifest.jsonl").read_text().splitlines()]
    expected = Counter({r.name: r.count for r in recipe_list})
    counts = Counter(r["recipe"] for r in rows)
    if recipes:
        require(counts == expected, f"recipe counts {counts} != {expected}")
    labels = {r["recipe"] for r in rows if r["recipe"]} | {r["preset"] for r in rows if r["preset"]}
    labels |= {"eshkol", "rngoddess", "moonlab"}
    provenance = {}
    if log:
        for line in Path(log).read_text().splitlines():
            item = json.loads(line)
            if item["event"] == "piece":
                provenance[item["id"]] = item
    require({p.name for p in out.iterdir()} == {"midi", "manifest.jsonl"}, "dataset has extra top-level files")
    require({p.relative_to(out).as_posix() for p in (out / "midi").rglob("*") if p.is_file()} == {r["path"] for r in rows},
            "MIDI inventory differs from manifest")
    seen, ids, durations, total_notes, compliant, automated, change_counts = set(), set(), [], 0, 0, 0, []
    extrema, control_values = [], {k: set() for k in ("key", "scale", "time_signature", "lanes", "bars", "start_tempo", "program")}
    targets = {r.name: r.fixed.get("duration") for r in recipe_list}
    fixed = {r.name: r.fixed for r in recipe_list}
    for row in rows:
        pid = row["id"]
        require(set(row) == MANIFEST_FIELDS, f"{pid}: wrong manifest fields")
        require(pid not in ids, f"duplicate ID {pid}")
        ids.add(pid)
        require(row["path"] == midi_path(int(pid)), f"{pid}: wrong shard path")
        data = (out / row["path"]).read_bytes()
        sha = hashlib.sha256(data).hexdigest()
        require(sha == row["sha256"] and sha not in seen, f"{pid}: SHA mismatch/duplicate")
        seen.add(sha)
        for label in labels:
            require(label.encode().lower() not in data.lower(), f"{pid}: label in MIDI bytes: {label}")
        mid = mido.MidiFile(file=io.BytesIO(data))
        require(len(mid.tracks) == len(row["lanes"]), f"{pid}: lane count mismatch")
        require(math.isclose(mid.length, row["duration_s"], abs_tol=1e-6), f"{pid}: duration mismatch")
        target = targets.get(row["recipe"])
        if target is not None:
            require(abs(mid.length - target) <= 2, f"{pid}: duration tolerance")
        durations.append(mid.length)
        num, den = map(int, row["time_signature"].split("/"))
        bar_ticks = num * 4 / den * mid.ticks_per_beat
        classes = {(KEYS.index(row["key"]) + i) % 12 for i in SCALES[row["scale"]]}
        note_count, tempos, signatures = 0, [], []
        logged = provenance.get(pid)
        if log:
            require(logged is not None, f"{pid}: missing provenance")
            require(logged["sha256"] == sha, f"{pid}: provenance mismatch")
        for lane, track in enumerate(mid.tracks):
            tick, active, program = 0, {}, None
            lane_info = row["lanes"][lane]
            lo, hi = lane_info["range"]
            for msg in track:
                tick += msg.time
                if msg.type == "track_name":
                    require(msg.name == f"lane {lane}", f"{pid}: non-neutral track name")
                require(msg.type not in ("text", "marker", "lyrics", "instrument_name", "copyright"), f"{pid}: unexpected text meta")
                if msg.type == "set_tempo":
                    require(lane == 0 and tick % bar_ticks == 0, f"{pid}: tempo off boundary/conductor")
                    tempos.append((tick, mido.tempo2bpm(msg.tempo)))
                if msg.type == "time_signature":
                    signatures.append(f"{msg.numerator}/{msg.denominator}")
                if msg.type == "program_change":
                    program = msg.program
                    control_values["program"].add(program)
                if msg.type == "note_on" and msg.velocity:
                    note_count += 1
                    require(msg.channel == lane_info["channel"], f"{pid}: channel mismatch")
                    require(msg.note % 12 in classes and lo <= msg.note <= hi, f"{pid}: note outside scale/range")
                    compliant += 1
                    active[(msg.channel, msg.note)] = tick
                    if logged:
                        vlo, vhi = logged["params"]["controls"]["velocity"]
                        require(vlo <= msg.velocity <= vhi, f"{pid}: velocity outside range")
                elif msg.type == "note_off" or (msg.type == "note_on" and not msg.velocity):
                    start = active.pop((msg.channel, msg.note), None)
                    require(start is not None and tick > start, f"{pid}: unmatched note-off")
                    if logged:
                        length = tick - start
                        allowed = [round(x * mid.ticks_per_beat) for x in logged["params"]["controls"]["lengths"]]
                        require(length in allowed or tick == row["bars"] * bar_ticks, f"{pid}: note length outside choices")
            require(not active, f"{pid}: hanging notes")
            require(tick == row["bars"] * bar_ticks, f"{pid}: track endpoint differs from bars")
            require(program == lane_info["program"], f"{pid}: program mismatch")
        require(signatures == [row["time_signature"]], f"{pid}: meter mismatch")
        require(note_count == row["note_count"], f"{pid}: note count mismatch")
        total_notes += note_count
        bpms = [bpm for _, bpm in tempos]
        require(bpms and tempos[0][0] == 0, f"{pid}: missing starting tempo")
        require(math.isclose(bpms[0], row["tempo"]["start"], abs_tol=1e-7), f"{pid}: starting tempo mismatch")
        if len(set(bpms)) > 1:
            require(row["tempo"].get("min") == min(bpms) and row["tempo"].get("max") == max(bpms), f"{pid}: tempo extrema mismatch")
        bounds = fixed.get(row["recipe"], {}).get("tempo_change_range")
        if bounds:
            require(all(bounds[0] <= bpm <= bounds[1] for bpm in bpms), f"{pid}: tempo out of bounds")
        if logged:
            require(len(tempos) == len(logged["params"]["tempo_map"]), f"{pid}: tempo event count")
            jump = logged["params"]["tempo_max_jump"]
            if jump is not None:
                require(all(abs(a-b) <= jump + 1e-9 for a, b in zip(bpms, bpms[1:])), f"{pid}: tempo jump exceeded")
        automated += len(tempos) > 1
        change_counts.append(len(tempos) - 1)
        extrema.extend(bpms)
        for field in ("key", "scale", "time_signature", "bars"):
            control_values[field].add(row[field])
        control_values["lanes"].add(len(row["lanes"]))
        control_values["start_tempo"].add(row["tempo"]["start"])
    require(len(rows) > 0, "empty dataset")
    return {"pieces": len(rows), "recipes": dict(counts), "distinct_sha256": len(seen),
            "notes": total_notes, "notes_in_scale_and_range": compliant,
            "compliance_percent": 100 * compliant / total_notes,
            "duration_s": {"min": min(durations), "max": max(durations), "mean": sum(durations)/len(durations)},
            "tempo_bpm": {"min": min(extrema), "max": max(extrema)}, "automated_pieces": automated,
            "tempo_changes": {"min": min(change_counts), "max": max(change_counts)},
            "control_distinct_counts": {k: len(v) for k, v in control_values.items()},
            "keys": sorted(control_values["key"]), "scales": sorted(control_values["scale"]),
            "meters": sorted(control_values["time_signature"]), "label_leaks": 0}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("out")
    ap.add_argument("--recipes")
    ap.add_argument("--log")
    args = ap.parse_args()
    try:
        print(json.dumps(verify_dataset(args.out, args.recipes, args.log), indent=2, sort_keys=True))
    except Exception as exc:
        print(f"verification failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
