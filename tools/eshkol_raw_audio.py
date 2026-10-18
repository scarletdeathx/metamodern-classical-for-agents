#!/usr/bin/env python3
"""Render raw entropy straight to a WAV (OWIE-style, never looped, never played).

Examples:
    python3 tools/eshkol_raw_audio.py --seconds 4 --out /tmp/raw.wav                 # moonlab, s16 48k mono
    python3 tools/eshkol_raw_audio.py --seconds 4 --bits 8 --rngoddess --out /tmp/owie.wav
    python3 tools/eshkol_raw_audio.py --rngoddess --source eshkol-local:moonlab --source system --out /tmp/mix.wav
    python3 tools/eshkol_raw_audio.py --source eshkol-local:synthetic --out /tmp/synth.wav
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from mcfa.raw_audio import DEFAULT_SOURCE, RawFormat, render_wav  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Raw entropy -> WAV (no DSP, no playback)")
    ap.add_argument("--seconds", type=float, default=4.0)
    ap.add_argument("--rate", type=int, default=48_000)
    ap.add_argument("--bits", type=int, choices=(8, 16), default=16)
    ap.add_argument("--channels", type=int, default=1)
    ap.add_argument("--gain", type=float, default=0.5)
    ap.add_argument("--source", dest="sources", action="append",
                    help=f"entropy source (default {DEFAULT_SOURCE}); repeatable with --rngoddess; "
                         "system, tsotchke-local, eshkol-local:<backend>; trailing ? = optional contributor")
    ap.add_argument("--rngoddess", action="store_true", help="mix sources with RNGoddess")
    ap.add_argument("--warm", action="store_true", help="prefill ~1 MiB before rendering (live-style)")
    ap.add_argument("--out", required=True, help="output .wav (sidecar .json written next to it)")
    args = ap.parse_args(argv)
    try:
        fmt = RawFormat(rate=args.rate, bits=args.bits, channels=args.channels, gain=args.gain)
        meta = render_wav(args.out, args.seconds, fmt, sources=args.sources,
                          rngoddess=args.rngoddess, warm=args.warm)
    except Exception as exc:
        print(f"render failed: {exc}", file=sys.stderr)
        return 1
    print(f"Wrote {meta['wav']} ({meta['seconds']:g} s, {fmt.bits}-bit {fmt.rate} Hz x{fmt.channels}) "
          f"from {meta['mode']} {meta['sources']}")
    print(f"raw {meta['raw_bytes']} bytes sha256:{meta['raw_sha256'][:16]}... underruns={meta['underruns']} "
          f"fill={meta['fill_rate_bytes_per_s']} B/s realtime x{meta['realtime_factor']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
