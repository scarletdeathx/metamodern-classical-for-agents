#!/usr/bin/env python3
"""Generate a MIDI training dataset (default: RNGoddess with eshkol-local:moonlab).

Examples:
    python3 tools/mcfa_dataset.py --count 20 --out /tmp/ds
    python3 tools/mcfa_dataset.py --count 1000 --out ~/ds --vary --resume
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
    ap.add_argument("--vary", action="store_true", help="pick lanes/bars per piece from the entropy")
    ap.add_argument("--lanes-range", type=_range, default=(1, 8))
    ap.add_argument("--bars-range", type=_range, default=(4, 16))
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
    try:
        summary = generate_dataset(
            args.out, args.count, lanes=args.lanes, bars=args.bars, vary=args.vary,
            lanes_range=args.lanes_range, bars_range=args.bars_range, rngoddess=args.rngoddess,
            sources=args.sources, backend=args.backend, seed_label=args.seed_label,
            resume=args.resume, log=print)
    except Exception as exc:
        print(f"dataset failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
