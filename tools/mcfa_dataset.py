#!/usr/bin/env python3
"""Generate a MIDI training dataset (default: RNGoddess with eshkol-local:moonlab).

Examples:
    python3 tools/mcfa_dataset.py --count 20 --out /tmp/ds
    python3 tools/mcfa_dataset.py --count 1000 --out ~/ds --vary --resume
    python3 tools/mcfa_dataset.py --count 200 --out ~/ds --vary --tempo-range 60-140 \
        --scales dorian,aeolian,lydian --keys all --time-signatures 4/4,3/4,7/8
    python3 tools/mcfa_dataset.py --count 50 --out /tmp/old --legacy          # original C1-C8 chromatic
    python3 tools/mcfa_dataset.py --count 50 --out /tmp/ds2 --no-rngoddess --backend synthetic
    python3 tools/mcfa_dataset.py --count 50 --out /tmp/ds3 --source eshkol-local:moonlab --source system
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from mcfa.dataset import generate_dataset  # noqa: E402
from mcfa.midi_controls import KEYS, TIME_SIGNATURES, VarySpec  # noqa: E402

import importlib.util  # noqa: E402

_spec = importlib.util.spec_from_file_location("eshkol_midi", Path(__file__).resolve().parent / "eshkol_midi.py")
eshkol_midi = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(eshkol_midi)  # type: ignore[union-attr]


def _range(text: str) -> tuple[int, int]:
    lo, _, hi = text.partition("-")
    lo_i, hi_i = int(lo), int(hi or lo)
    if lo_i < 1 or hi_i < lo_i:
        raise argparse.ArgumentTypeError("use MIN-MAX with 1 <= MIN <= MAX")
    return lo_i, hi_i


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="MCFA MIDI training-dataset generator (no playback)")
    choice = ap.add_mutually_exclusive_group(required=True)
    choice.add_argument("--count", type=int)
    choice.add_argument("--recipes", help="YAML/JSON recipe file; counts are taken from recipes")
    ap.add_argument("--log", help="optional provenance JSONL outside dataset; also writes PATH.summary.md")
    ap.add_argument("--duration", type=float, help="target seconds, whole bars, tolerance +/-2 s")
    ap.add_argument("--tempo-changes", type=int, default=0, help="N additional set_tempo events at bar boundaries")
    ap.add_argument("--tempo-change-range", help="automation BPM MIN-MAX")
    ap.add_argument("--tempo-max-jump", type=float, help="maximum BPM change per automation event")
    ap.add_argument("--out", required=True)
    motion = ap.add_argument_group("dense motion (opt-in; recipes use fixed.motion)")
    motion.add_argument("--min-notes-per-sec", type=float)
    motion.add_argument("--max-gap-s", type=float)
    motion.add_argument("--note-step-beats", type=float)
    motion.add_argument("--tempo-interval-beats", type=float)
    motion.add_argument("--harmony-interval-beats", type=float)
    motion.add_argument("--cc-interval-beats", type=float)
    motion.add_argument("--pitch-bend-interval-beats", type=float)
    motion.add_argument("--harmony-keys", help="comma list or all")
    motion.add_argument("--harmony-scales", help="comma list or all")
    motion.add_argument("--chord-sizes", help="comma list, 1..4 notes per lane chord")
    ap.add_argument("--lanes", type=int, default=4)
    ap.add_argument("--bars", type=int, default=8)
    ap.add_argument("--vary", action="store_true",
                    help="draw per piece from the entropy: lanes/bars ranges plus any vary flags below")
    ap.add_argument("--lanes-range", type=_range, default=(1, 8))
    ap.add_argument("--bars-range", type=_range, default=(4, 16))
    v = ap.add_argument_group("per-piece variation (with --vary)")
    v.add_argument("--tempo-range", help="BPM MIN-MAX, e.g. 60-140")
    v.add_argument("--scales", help="comma list of scales, or 'all'")
    v.add_argument("--keys", help="comma list of roots, or 'all'")
    v.add_argument("--time-signatures", help="comma list, or 'all' (" + ",".join(TIME_SIGNATURES) + ")")
    v.add_argument("--rest-range", help="rest probability MIN-MAX, e.g. 0.05-0.4")
    v.add_argument("--velocity-choices", help='JSON list of velocity pairs, e.g. [[1,64],[64,127]]')
    v.add_argument("--length-choices", help='JSON list of beat-length sets')
    v.add_argument("--lane-range-choices", help='JSON list of per-lane range layouts')
    v.add_argument("--program-choices", help='JSON list of per-lane program lists')
    v.add_argument("--tempo-changes-range", type=_range, help="number of automation changes MIN-MAX")
    v.add_argument("--tempo-jump-range", help="per-piece maximum tempo jump MIN-MAX")
    eshkol_midi.add_control_args(ap)
    ap.add_argument("--rngoddess", dest="rngoddess", action="store_true", default=True)
    ap.add_argument("--no-rngoddess", dest="rngoddess", action="store_false",
                    help="draw straight from one drawd backend instead of the mixer")
    ap.add_argument("--source", dest="sources", action="append",
                    help="RNGoddess contributor (repeatable; default eshkol-local:moonlab)")
    ap.add_argument("--backend", default="moonlab", help="drawd backend with --no-rngoddess")
    ap.add_argument("--seed-label", default="piece")
    ap.add_argument("--resume", action="store_true", help="skip pieces already written")
    args = ap.parse_args(argv)
    if not 1 <= args.lanes_range[1] <= 16 or not 1 <= args.lanes <= 16:
        ap.error("lanes must be 1..16")
    if args.sources and not args.rngoddess:
        ap.error("--source needs RNGoddess mode")
    def _list(text, everything):
        if not text:
            return None
        return list(everything) if text.strip().lower() == "all" else [x.strip() for x in text.split(",") if x.strip()]

    from mcfa.midi_controls import SCALES
    try:
        spec = VarySpec(
            tempo_range=tuple(float(x) for x in args.tempo_range.split("-")) if args.tempo_range else None,
            scales=_list(args.scales, sorted(SCALES)),
            keys=_list(args.keys, KEYS),
            time_signatures=_list(args.time_signatures, TIME_SIGNATURES),
            rest_range=tuple(float(x) for x in args.rest_range.split("-")) if args.rest_range else None,
            velocity_choices=json.loads(args.velocity_choices) if args.velocity_choices else None,
            length_choices=json.loads(args.length_choices) if args.length_choices else None,
            lane_range_choices=json.loads(args.lane_range_choices) if args.lane_range_choices else None,
            program_choices=json.loads(args.program_choices) if args.program_choices else None,
            tempo_changes_range=args.tempo_changes_range,
            tempo_jump_range=tuple(float(x) for x in args.tempo_jump_range.split("-")) if args.tempo_jump_range else None,
        ).validate()
    except (TypeError, ValueError) as exc:
        ap.error(str(exc))
    if args.recipes and (args.vary or any(vars(spec).values())):
        ap.error("with --recipes, put variation in the recipe file")
    if not args.vary and any(vars(spec).values()):
        ap.error("variation flags need --vary")
    try:
        motion_fields = ("min_notes_per_sec", "max_gap_s", "note_step_beats", "tempo_interval_beats",
                         "harmony_interval_beats", "cc_interval_beats", "pitch_bend_interval_beats")
        motion_config = {k: getattr(args, k) for k in motion_fields if getattr(args, k) is not None}
        for field in ("harmony_keys", "harmony_scales"):
            value = getattr(args, field)
            if value:
                motion_config[field] = "all" if value == "all" else value.split(",")
        if args.chord_sizes:
            motion_config["chord_sizes"] = [int(x) for x in args.chord_sizes.split(",")]
        controls = None if args.legacy else eshkol_midi.controls_from_args(args)
        summary = generate_dataset(
            args.out, args.count, lanes=args.lanes, bars=args.bars, vary=args.vary,
            lanes_range=args.lanes_range, bars_range=args.bars_range, rngoddess=args.rngoddess,
            sources=args.sources, backend=args.backend, seed_label=args.seed_label,
            resume=args.resume, log=args.log, progress=print, controls=controls, vary_spec=spec if args.vary else None,
            legacy=args.legacy, recipes=args.recipes, duration=args.duration,
            tempo_changes=args.tempo_changes,
            tempo_change_range=tuple(float(x) for x in args.tempo_change_range.split("-")) if args.tempo_change_range else None,
            tempo_max_jump=args.tempo_max_jump, motion=motion_config or None)
    except Exception as exc:
        print(f"dataset failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
