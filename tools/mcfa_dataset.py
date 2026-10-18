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
    ap.add_argument("--count", type=int, required=True)
    ap.add_argument("--out", required=True)
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
    spec = VarySpec(
        tempo_range=tuple(float(x) for x in args.tempo_range.split("-")) if args.tempo_range else None,
        scales=_list(args.scales, sorted(SCALES)),
        keys=_list(args.keys, KEYS),
        time_signatures=_list(args.time_signatures, TIME_SIGNATURES),
        rest_range=tuple(float(x) for x in args.rest_range.split("-")) if args.rest_range else None,
    )
    if not args.vary and any(vars(spec).values()):
        ap.error("variation flags need --vary")
    try:
        controls = None if args.legacy else eshkol_midi.controls_from_args(args)
        summary = generate_dataset(
            args.out, args.count, lanes=args.lanes, bars=args.bars, vary=args.vary,
            lanes_range=args.lanes_range, bars_range=args.bars_range, rngoddess=args.rngoddess,
            sources=args.sources, backend=args.backend, seed_label=args.seed_label,
            resume=args.resume, log=print, controls=controls, vary_spec=spec if args.vary else None,
            legacy=args.legacy)
    except Exception as exc:
        print(f"dataset failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
