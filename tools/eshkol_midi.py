#!/usr/bin/env python3
"""Generate Eshkol-randomized MIDI for VWSD-RNGoddess training data.

Pulls entropy draws from local drawd and maps them to MIDI note
parameters (pitch, timing, velocity, duration). Each "lane" draws from
an independent byte range so lanes don't perturb each other -- this
preserves MCFA's named-independent-domains contract.

Output is a standard .mid file (via mido) plus a JSON sidecar with
provenance for every draw used.

Usage:
    python3 eshkol_midi.py --lanes 4 --bars 8 --output training_001.mid            # moonlab (default)
    python3 eshkol_midi.py --lanes 4 --bars 8 --output training_001.mid --backend synthetic

Requires: mido, drawd running locally (127.0.0.1:18751 or /tmp/eshkol-drawd.sock)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from mcfa.providers.eshkol import draw_from_drawd, DEFAULT_BACKEND  # noqa: E402


# MIDI mapping constants
PITCH_MIN, PITCH_MAX = 24, 108  # C1 to C8
VELOCITY_MIN, VELOCITY_MAX = 20, 127
TICKS_PER_BEAT = 480
BEATS_PER_BAR = 4


def bytes_to_notes(data: bytes, lane_id: int) -> list[dict]:
    """Map a byte stream to MIDI note events for one lane.

    Each note consumes 4 bytes:
        byte 0: pitch (mapped to PITCH_MIN..PITCH_MAX)
        byte 1: velocity (mapped to VELOCITY_MIN..VELOCITY_MAX)
        byte 2: duration in ticks (mapped to 60..960, i.e. 32nd note to 2 beats)
        byte 3: gap after note in ticks (mapped to 0..480, i.e. 0 to 1 beat)
    """
    notes = []
    tick = 0
    for i in range(0, len(data) - 3, 4):
        pitch = PITCH_MIN + (data[i] % (PITCH_MAX - PITCH_MIN + 1))
        velocity = VELOCITY_MIN + (data[i + 1] % (VELOCITY_MAX - VELOCITY_MIN + 1))
        duration = 60 + (data[i + 2] % 901)  # 60..960 ticks
        gap = data[i + 3] % 481  # 0..480 ticks

        notes.append({
            "pitch": pitch,
            "velocity": velocity,
            "start_tick": tick,
            "duration_ticks": duration,
            "lane": lane_id,
        })
        tick += duration + gap
    return notes


def generate_midi(
    lanes: int,
    bars: int,
    backend: str = DEFAULT_BACKEND,
    seed_tag: str = "",
) -> tuple["mido.MidiFile", dict]:
    """Generate a multi-lane MIDI file from Eshkol draws."""
    import mido

    total_beats = bars * BEATS_PER_BAR
    # Estimate: ~4 notes per beat per lane, 4 bytes per note
    bytes_per_lane = total_beats * 4 * 4

    mid = mido.MidiFile(ticks_per_beat=TICKS_PER_BEAT)
    provenance = {
        "backend": backend,
        "lanes": lanes,
        "bars": bars,
        "seed_tag": seed_tag,
        "draws": [],
    }

    for lane_id in range(lanes):
        # Independent domain per lane: separate drawd call per lane
        data = draw_from_drawd(bytes_per_lane, backend=backend)
        draw_hash = hashlib.sha256(data).hexdigest()
        provenance["draws"].append({
            "lane": lane_id,
            "bytes": len(data),
            "sha256": draw_hash,
            "provider": f"eshkol-{backend}",
        })

        notes = bytes_to_notes(data, lane_id)
        track = mido.MidiTrack()
        track.name = f"eshkol-lane-{lane_id:02d}"
        mid.tracks.append(track)

        # Sort by start tick and emit note_on/note_off with deltas
        events = []
        for n in notes:
            # Stop at the bar boundary
            if n["start_tick"] >= total_beats * TICKS_PER_BEAT:
                break
            events.append((n["start_tick"], "on", n))
            events.append((n["start_tick"] + n["duration_ticks"], "off", n))
        events.sort(key=lambda e: (e[0], 0 if e[1] == "off" else 1))

        last_tick = 0
        for tick, kind, n in events:
            delta = tick - last_tick
            if kind == "on":
                track.append(mido.Message(
                    "note_on", note=n["pitch"], velocity=n["velocity"],
                    time=delta, channel=lane_id % 16,
                ))
            else:
                track.append(mido.Message(
                    "note_off", note=n["pitch"], velocity=0,
                    time=delta, channel=n["lane"] % 16,
                ))
            last_tick = tick

    return mid, provenance


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Eshkol-randomized MIDI generator")
    ap.add_argument("--lanes", type=int, default=4, help="number of independent lanes")
    ap.add_argument("--bars", type=int, default=8, help="bars per lane")
    ap.add_argument("--output", type=str, required=True, help="output .mid path")
    ap.add_argument("--backend", type=str, default=DEFAULT_BACKEND,
                    help="drawd backend name (default: moonlab, or $ESHKOL_DRAWD_BACKEND)")
    ap.add_argument("--tag", type=str, default="", help="seed tag for provenance")
    args = ap.parse_args(argv)

    if not 1 <= args.lanes <= 16:
        print("lanes must be 1..16", file=sys.stderr)
        return 1
    if args.bars < 1:
        print("bars must be >= 1", file=sys.stderr)
        return 1

    try:
        import mido  # noqa: F401
    except ImportError:
        print("mido is required: pip install mido", file=sys.stderr)
        return 1

    print(f"Drawing Eshkol entropy (backend={args.backend}) for "
          f"{args.lanes} lanes x {args.bars} bars...", flush=True)
    try:
        mid, provenance = generate_midi(args.lanes, args.bars,
                                        backend=args.backend, seed_tag=args.tag)
    except Exception as exc:
        print(f"draw failed: {exc}", file=sys.stderr)
        return 1

    out = Path(args.output)
    mid.save(str(out))
    sidecar = out.with_suffix(".json")
    sidecar.write_text(json.dumps(provenance, indent=2))

    total_notes = sum(len(t) for t in mid.tracks)
    print(f"Wrote {out} ({len(mid.tracks)} tracks)")
    print(f"Provenance: {sidecar}")
    for d in provenance["draws"]:
        print(f"  lane {d['lane']:02d}: {d['bytes']} bytes sha256:{d['sha256'][:16]}...")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
