"""Batch MIDI training-dataset generator built on tools/eshkol_midi.py.

Layout under the output directory:
    midi/NNNNNN.mid      one piece per file (written atomically)
    meta/NNNNNN.json     params, per-lane provenance (+ RNGoddess manifests),
                         MIDI sha256, note/track counts, duration
    manifest.jsonl       one line per accepted piece (rebuilt from meta/ at the end)
    rejects.jsonl        rejected attempts (malformed, empty, duplicate)
    dataset_card.md      generated from facts only

Only the knobs eshkol_midi already has are used (lanes, bars). With
vary=True they are chosen per piece from the entropy source itself and the
draw is logged in the piece metadata. No musical content is added here.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import importlib.util
import io
import json
import os
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any, Callable

_TOOL = Path(__file__).resolve().parents[2] / "tools" / "eshkol_midi.py"
SCHEMA = "mcfa-midi-dataset/v1"
MAX_ATTEMPTS = 3

# draw_fn(n_bytes, lane_id, piece_tag) -> (bytes, provenance entry dict)
DrawFn = Callable[[int, int, str], tuple[bytes, dict]]


def _load_tool():
    spec = importlib.util.spec_from_file_location("eshkol_midi", _TOOL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix="." + path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def validate_midi(data: bytes) -> dict[str, Any]:
    """Re-parse with mido; raise ValueError if malformed or empty."""
    import mido

    try:
        mid = mido.MidiFile(file=io.BytesIO(data))
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"malformed MIDI: {exc}") from exc
    notes = sum(1 for t in mid.tracks for m in t if m.type == "note_on" and m.velocity > 0)
    if not mid.tracks or notes == 0:
        raise ValueError("empty MIDI (no notes)")
    return {"tracks": len(mid.tracks), "notes": notes, "duration_s": round(mid.length, 3),
            "ticks_per_beat": mid.ticks_per_beat, "midi_type": mid.type}


def git_commit() -> str | None:
    try:
        out = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=_TOOL.parent,
                             capture_output=True, text=True, timeout=5)
        dirty = subprocess.run(["git", "status", "--porcelain", "--untracked-files=no"], cwd=_TOOL.parent,
                               capture_output=True, text=True, timeout=5).stdout.strip()
        return out.stdout.strip() + ("-dirty" if dirty else "") if out.returncode == 0 else None
    except Exception:  # noqa: BLE001
        return None


def default_draw_fn(rngoddess: bool, sources: list[str] | None, backend: str) -> DrawFn:
    if rngoddess:
        from .providers.mixer import RNGoddessMixer

        def draw(n: int, lane: int, tag: str):
            label = f"mcfa/v2/rngoddess/dataset/{tag}/" + ("params" if lane < 0 else f"lane/{lane:02d}")
            m = RNGoddessMixer(sources, label=label)
            data = m.read(n).data
            return data, {"provider": "rngoddess", "manifest": m.provenance()}
        return draw

    from .providers.eshkol import draw_from_drawd

    def draw(n: int, lane: int, tag: str):
        return draw_from_drawd(n, backend=backend), {"provider": f"eshkol-{backend}"}
    return draw


def _vary(draw: DrawFn, tag: str, lanes_range, bars_range) -> tuple[int, int, dict]:
    data, entry = draw(32, -1, tag)
    lanes = lanes_range[0] + data[0] % (lanes_range[1] - lanes_range[0] + 1)
    bars = bars_range[0] + data[1] % (bars_range[1] - bars_range[0] + 1)
    return lanes, bars, {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
                         "lanes_byte": data[0], "bars_byte": data[1], **entry}


def generate_dataset(
    out_dir: str | Path,
    count: int,
    *,
    lanes: int = 4,
    bars: int = 8,
    vary: bool = False,
    lanes_range: tuple[int, int] = (1, 8),
    bars_range: tuple[int, int] = (4, 16),
    rngoddess: bool = True,
    sources: list[str] | None = None,
    backend: str = "moonlab",
    seed_label: str = "piece",
    resume: bool = False,
    draw_fn: DrawFn | None = None,
    log: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    tool = _load_tool()
    out = Path(out_dir)
    (out / "midi").mkdir(parents=True, exist_ok=True)
    (out / "meta").mkdir(parents=True, exist_ok=True)
    if any((out / "meta").glob("*.json")) and not resume:
        raise FileExistsError(f"{out} already has pieces; pass resume=True to continue")
    if rngoddess and sources is None:
        sources = ["eshkol-local:moonlab"]
    draw = draw_fn or default_draw_fn(rngoddess, sources, backend)
    source_desc = {"mode": "rngoddess" if rngoddess else "single-source",
                   "sources": sources if rngoddess else [f"eshkol-local:{backend}"]}

    seen: dict[str, str] = {}
    for meta_path in sorted((out / "meta").glob("*.json")):
        meta = json.loads(meta_path.read_text())
        seen[meta["midi_sha256"]] = meta["id"]

    made = skipped = rejected = 0
    times: list[float] = []
    for i in range(count):
        pid = f"{i:06d}"
        midi_path, meta_path = out / "midi" / f"{pid}.mid", out / "meta" / f"{pid}.json"
        if meta_path.exists() and midi_path.exists():
            skipped += 1
            continue
        t0 = time.monotonic()
        for attempt in range(1, MAX_ATTEMPTS + 1):
            tag = f"{seed_label}-{pid}" + (f"-r{attempt}" if attempt > 1 else "")
            params: dict[str, Any] = {"lanes": lanes, "bars": bars, "vary": vary}
            if vary:
                params["lanes"], params["bars"], params["vary_draw"] = _vary(draw, tag, lanes_range, bars_range)
                params["lanes_range"], params["bars_range"] = list(lanes_range), list(bars_range)
            mid, prov = tool.generate_midi(params["lanes"], params["bars"], seed_tag=tag,
                                           draw_fn=lambda n, lane: draw(n, lane, tag))
            buf = io.BytesIO()
            mid.save(file=buf)
            data = buf.getvalue()
            sha = hashlib.sha256(data).hexdigest()
            reason = None
            try:
                stats = validate_midi(data)
            except ValueError as exc:
                reason = str(exc)
            if reason is None and sha in seen:
                reason = f"duplicate of {seen[sha]}"
            if reason is None:
                break
            rejected += 1
            with open(out / "rejects.jsonl", "a") as f:
                f.write(json.dumps({"id": pid, "attempt": attempt, "tag": tag, "reason": reason,
                                    "midi_sha256": sha}) + "\n")
            if log:
                log(f"reject {pid} attempt {attempt}: {reason}")
        else:
            raise RuntimeError(f"piece {pid} rejected {MAX_ATTEMPTS} times; see rejects.jsonl")

        meta = {
            "schema": SCHEMA, "id": pid, "seed_label": tag, "attempt": attempt,
            "params": params, "source": source_desc,
            "midi": f"midi/{pid}.mid", "midi_sha256": sha, "midi_bytes": len(data), **stats,
            "lanes_provenance": prov["draws"],
            "generator": {"tool": "tools/eshkol_midi.py", "commit": git_commit()},
            "created_at": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
        }
        atomic_write(midi_path, data)
        atomic_write(meta_path, json.dumps(meta, indent=2).encode())
        seen[sha] = pid
        made += 1
        times.append(time.monotonic() - t0)
        if log:
            log(f"{pid}: {stats['notes']} notes, {stats['duration_s']} s, {params['lanes']} lanes x {params['bars']} bars")

    summary = finalize(out)
    summary.update({"made": made, "skipped": skipped, "rejected": rejected,
                    "seconds_per_piece": round(sum(times) / len(times), 3) if times else None})
    return summary


def finalize(out: Path) -> dict[str, Any]:
    """Rebuild manifest.jsonl and dataset_card.md from meta/ (facts only)."""
    metas = [json.loads(p.read_text()) for p in sorted((out / "meta").glob("*.json"))]
    lines = "".join(json.dumps({k: m[k] for k in ("id", "midi", "midi_sha256", "notes", "duration_s",
                                                   "tracks", "seed_label", "params", "source")}) + "\n"
                    for m in metas)
    atomic_write(out / "manifest.jsonl", lines.encode())
    n = len(metas)
    rng = lambda key, f=lambda m, k: m[k]: (min(f(m, key) for m in metas), max(f(m, key) for m in metas)) if metas else (None, None)
    p = lambda m, k: m["params"][k]
    sources = sorted({json.dumps(m["source"], sort_keys=True) for m in metas})
    commits = sorted({str(m["generator"]["commit"]) for m in metas})
    rejects = out / "rejects.jsonl"
    nrej = len(rejects.read_text().splitlines()) if rejects.exists() else 0
    total = sum(m["midi_bytes"] for m in metas)
    card = f"""# MCFA MIDI dataset

- Generated: {_dt.date.today().isoformat()}
- Schema: {SCHEMA}
- Pieces: {n} (distinct MIDI sha256: {len({m['midi_sha256'] for m in metas})})
- Rejected attempts: {nrej}
- Total MIDI size: {total} bytes
- Format: Standard MIDI File type {metas[0]['midi_type'] if metas else '-'}, {metas[0]['ticks_per_beat'] if metas else '-'} ticks per beat, one track per lane
- Generator: tools/eshkol_midi.py via src/mcfa/dataset.py, commit(s) {', '.join(commits) or '-'}
- Entropy source(s): {'; '.join(sources) or '-'}

## Ranges

| field | min | max |
|---|---|---|
| lanes | {rng('lanes', p)[0]} | {rng('lanes', p)[1]} |
| bars | {rng('bars', p)[0]} | {rng('bars', p)[1]} |
| notes | {rng('notes')[0]} | {rng('notes')[1]} |
| duration (s) | {rng('duration_s')[0]} | {rng('duration_s')[1]} |
| tracks | {rng('tracks')[0]} | {rng('tracks')[1]} |

Files: `midi/NNNNNN.mid`, `meta/NNNNNN.json`, `manifest.jsonl`{', `rejects.jsonl`' if nrej else ''}.
"""
    atomic_write(out / "dataset_card.md", card.encode())
    return {"pieces": n, "distinct_sha256": len({m["midi_sha256"] for m in metas}), "total_bytes": total,
            "notes_range": rng("notes"), "duration_range": rng("duration_s"), "rejects_total": nrej}
