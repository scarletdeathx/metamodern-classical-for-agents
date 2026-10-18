#!/usr/bin/env python3
"""Generate Eshkol-randomized MIDI for VWSD-RNGoddess training data.

Pulls entropy draws from local drawd and maps them to MIDI note
parameters (pitch, timing, velocity, duration). Each "lane" draws from
an independent byte range so lanes don't perturb each other -- this
preserves MCFA's named-independent-domains contract.

Output is a standard .mid file (via mido) plus a JSON sidecar with
provenance for every draw used.

Usage:
    python3 eshkol_midi.py --lanes 4 --bars 8 --output out.mid                 # A aeolian, 120 BPM, 4/4
    python3 eshkol_midi.py --tempo 90 --key D --scale dorian --time-signature 7/8 --output out.mid
    python3 eshkol_midi.py --rngoddess --lane-range C2-C4 --lane-range G3-G5 --program 33 --program 0 --output out.mid
    python3 eshkol_midi.py --legacy --backend synthetic --output old.mid       # original C1-C8 chromatic mapping

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
from mcfa.midi_controls import (  # noqa: E402
    KEYS, SCALES, SCALE_ALIASES, MidiControls, bytes_needed, lane_notes, midi_channel,
    parse_range,
)


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


def _emit_track(track, notes, channel, mido, end_tick=None, tempo_events=None) -> None:
    events = []
    for n in notes:
        events.append((n["start_tick"], 1, "on", n))
        events.append((n["start_tick"] + n["duration_ticks"], 0, "off", n))
    for tick, tempo in tempo_events or []:
        events.append((tick, -1, "tempo", tempo))
    events.sort(key=lambda e: (e[0], e[1]))
    last_tick = 0
    for tick, _, kind, n in events:
        if kind == "tempo":
            track.append(mido.MetaMessage("set_tempo", tempo=n, time=tick - last_tick))
            last_tick = tick
            continue
        track.append(mido.Message(
            "note_on" if kind == "on" else "note_off", note=n["pitch"],
            velocity=n["velocity"] if kind == "on" else 0, time=tick - last_tick, channel=channel,
        ))
        last_tick = tick
    if end_tick is not None and end_tick >= last_tick:
        # pad trailing rests so every lane spans exactly the requested bars
        track.append(mido.MetaMessage("end_of_track", time=end_tick - last_tick))


def generate_midi(
    lanes: int,
    bars: int,
    backend: str = DEFAULT_BACKEND,
    seed_tag: str = "",
    rngoddess_sources: list[str] | None = None,
    rngoddess: bool = False,
    draw_fn=None,
    controls: MidiControls | None = None,
    legacy: bool = False,
    tempo_events: list[tuple[int, int]] | None = None,
) -> tuple["mido.MidiFile", dict]:
    """Generate a multi-lane MIDI file from Eshkol draws.

    Default: musically constrained output from ``controls`` (MidiControls()).
    ``legacy=True`` reproduces the original C1-C8 chromatic byte mapping.
    """
    import mido

    if not legacy:
        controls = (controls or MidiControls()).validate()
        bytes_per_lane = bytes_needed(controls, bars)
    else:
        bytes_per_lane = bars * BEATS_PER_BAR * 4 * 4
    total_ticks = (round(bars * controls.beats_per_bar * TICKS_PER_BEAT) if not legacy
                   else bars * BEATS_PER_BAR * TICKS_PER_BEAT)

    mid = mido.MidiFile(ticks_per_beat=TICKS_PER_BEAT)
    provenance = {
        "backend": "rngoddess" if rngoddess else backend,
        "lanes": lanes,
        "bars": bars,
        "seed_tag": seed_tag,
        "legacy": legacy,
        "controls": None if legacy else controls.public(),
        "lane_layout": [],
        "draws": [],
    }

    for lane_id in range(lanes):
        if draw_fn is not None:
            data, entry = draw_fn(bytes_per_lane, lane_id)
        elif rngoddess:
            from mcfa.providers.mixer import RNGoddessMixer

            mixer = RNGoddessMixer(rngoddess_sources,
                                   label=f"mcfa/v2/rngoddess/midi/{seed_tag + '/' if seed_tag else ''}lane/{lane_id:02d}")
            data = mixer.read(bytes_per_lane).data
            entry = {"provider": "rngoddess", "manifest": mixer.provenance()}
        else:
            data = draw_from_drawd(bytes_per_lane, backend=backend)
            entry = {"provider": f"eshkol-{backend}"}
        provenance["draws"].append({
            "lane": lane_id, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(), **entry,
        })

        track = mido.MidiTrack()
        track.name = f"lane {lane_id}"
        mid.tracks.append(track)
        if legacy:
            channel = lane_id % 16
            # original behaviour: stop at the first note starting past the end
            out = []
            for n in bytes_to_notes(data, lane_id):
                if n["start_tick"] >= total_ticks:
                    break
                out.append(n)
            notes = out
        else:
            channel = midi_channel(lane_id)
            if lane_id == 0:
                num, den = (int(x) for x in controls.time_signature.split("/"))
                if tempo_events is None:
                    track.append(mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(controls.tempo), time=0))
                track.append(mido.MetaMessage("time_signature", numerator=num, denominator=den, time=0))
            program = controls.program(lane_id)
            if program is not None:
                track.append(mido.Message("program_change", program=program, channel=channel, time=0))
            notes = lane_notes(data, lane_id, bars, controls)
            lo, hi = controls.lane_range(lane_id)
            provenance["lane_layout"].append({
                "lane": lane_id, "role": controls.role(lane_id), "range": [lo, hi],
                "channel": channel, "program": program, "notes": len(notes),
            })
        _emit_track(track, notes, channel, mido, end_tick=None if legacy else total_ticks,
                    tempo_events=tempo_events if lane_id == 0 else None)

    return mid, provenance


def _floats(text: str) -> tuple[float, ...]:
    return tuple(float(x) for x in text.split(",") if x.strip())


def _pair(text: str, cast=int):
    lo, _, hi = text.partition("-")
    return cast(lo), cast(hi or lo)


def add_control_args(ap: argparse.ArgumentParser) -> None:
    """Shared musical-control flags (also used by tools/mcfa_dataset.py)."""
    g = ap.add_argument_group("musical controls")
    g.add_argument("--tempo", type=float, default=120.0, help="BPM (20..400), written as set_tempo")
    g.add_argument("--time-signature", default="4/4", help="e.g. 4/4, 3/4, 7/8")
    g.add_argument("--key", default="A", help="root: C, C#, Db ... B (default A)")
    g.add_argument("--scale", default="aeolian",
                   help="one of " + ", ".join(sorted(SCALES) + sorted(SCALE_ALIASES)))
    g.add_argument("--rest-probability", type=float, default=0.15)
    g.add_argument("--velocity-range", default="40-110", help="MIDI velocity LOW-HIGH")
    g.add_argument("--lengths", default="0.25,0.5,1,2", help="note lengths in beats (comma list)")
    g.add_argument("--lane-range", action="append", dest="lane_ranges",
                   help="per-lane pitch range LOW-HIGH (C2-C4 or 36-60), repeatable, cycled; "
                        "default bass/tenor/alto/soprano registers")
    g.add_argument("--program", action="append", type=int, dest="programs",
                   help="per-lane GM program 0..127, repeatable, cycled")
    g.add_argument("--legacy", action="store_true", help="original C1-C8 chromatic mapping")


def controls_from_args(args) -> MidiControls:
    return MidiControls(
        tempo=args.tempo, time_signature=args.time_signature, key=args.key, scale=args.scale,
        rest_probability=args.rest_probability, velocity=_pair(args.velocity_range),
        lengths=_floats(args.lengths),
        lane_ranges=[parse_range(r) for r in args.lane_ranges] if args.lane_ranges else None,
        programs=args.programs,
    ).validate()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Eshkol-randomized MIDI generator")
    ap.add_argument("--lanes", type=int, default=4, help="number of independent lanes")
    ap.add_argument("--bars", type=int, default=8, help="bars per lane")
    ap.add_argument("--output", type=str, required=True, help="output .mid path")
    ap.add_argument("--backend", type=str, default=DEFAULT_BACKEND, help="drawd backend name")
    ap.add_argument("--rngoddess", action="store_true",
                    help="mix contributors with RNGoddess (default contributor eshkol-local:moonlab)")
    ap.add_argument("--source", dest="sources", action="append",
                    help="RNGoddess contributor, repeatable (system, tsotchke-local, "
                         "eshkol-local:<backend>; trailing ? = optional)")
    ap.add_argument("--tag", type=str, default="", help="seed tag for provenance")
    add_control_args(ap)
    args = ap.parse_args(argv)

    if not 1 <= args.lanes <= 16:
        print("lanes must be 1..16", file=sys.stderr)
        return 1
    if args.bars < 1:
        print("bars must be >= 1", file=sys.stderr)
        return 1
    if args.sources and not args.rngoddess:
        print("--source requires --rngoddess", file=sys.stderr)
        return 1
    try:
        import mido  # noqa: F401
    except ImportError:
        print("mido is required: pip install mido", file=sys.stderr)
        return 1
    try:
        controls = None if args.legacy else controls_from_args(args)
    except Exception as exc:
        print(f"bad controls: {exc}", file=sys.stderr)
        return 1

    what = "RNGoddess mix" if args.rngoddess else f"Eshkol entropy (backend={args.backend})"
    print(f"Drawing {what} for {args.lanes} lanes x {args.bars} bars...", flush=True)
    try:
        mid, provenance = generate_midi(args.lanes, args.bars, backend=args.backend, seed_tag=args.tag,
                                        rngoddess=args.rngoddess, rngoddess_sources=args.sources,
                                        controls=controls, legacy=args.legacy)
    except Exception as exc:
        print(f"draw failed: {exc}", file=sys.stderr)
        return 1

    out = Path(args.output)
    mid.save(str(out))
    sidecar = out.with_suffix(".json")
    sidecar.write_text(json.dumps(provenance, indent=2))
    print(f"Wrote {out} ({len(mid.tracks)} tracks)")
    print(f"Provenance: {sidecar}")
    for d in provenance["draws"]:
        print(f"  lane {d['lane']:02d}: {d['bytes']} bytes sha256:{d['sha256'][:16]}...")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
