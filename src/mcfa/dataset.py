"""Silent MIDI datasets: only sharded MIDI and manifest.jsonl in the dataset.

Optional external JSONL logs hold provenance and rejected attempts. All musical
entropy comes through the caller's draw function (normally RNGoddess/Eshkol).
Recovery trusts parsed MIDI facts; absent intent is null, never guessed.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import asdict, replace
import datetime as _dt
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
from typing import Any, Callable

_TOOL = Path(__file__).resolve().parents[2] / "tools" / "eshkol_midi.py"
SCHEMA = "mcfa-midi-dataset/v2"
MAX_ATTEMPTS = 16
DrawFn = Callable[[int, int, str], tuple[bytes, dict]]
MANIFEST_FIELDS = {"id", "path", "sha256", "recipe", "preset", "tempo", "key", "scale",
                   "time_signature", "lanes", "bars", "duration_s", "note_count"}


def _load_tool():
    spec = importlib.util.spec_from_file_location("eshkol_midi", _TOOL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
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


def midi_path(index: int) -> str:
    return f"midi/{index // 1000:03d}/{index:06d}.mid"


def _parse(data):
    import mido
    try:
        return mido.MidiFile(file=io.BytesIO(data))
    except Exception as exc:
        raise ValueError(f"malformed MIDI: {exc}") from exc


def validate_midi(data: bytes) -> dict[str, Any]:
    mid = _parse(data)
    notes = sum(m.type == "note_on" and m.velocity > 0 for t in mid.tracks for m in t)
    if not mid.tracks or not notes:
        raise ValueError("empty MIDI (no notes)")
    return {"tracks": len(mid.tracks), "notes": notes, "duration_s": mid.length,
            "ticks_per_beat": mid.ticks_per_beat, "midi_type": mid.type}


def git_commit() -> str | None:
    try:
        out = subprocess.run(["git", "rev-parse", "HEAD"], cwd=_TOOL.parent,
                             capture_output=True, text=True, timeout=5)
        dirty = subprocess.run(["git", "status", "--porcelain", "--untracked-files=no"], cwd=_TOOL.parent,
                               capture_output=True, text=True, timeout=5).stdout.strip()
        return out.stdout.strip() + ("-dirty" if dirty else "") if out.returncode == 0 else None
    except Exception:
        return None


def default_draw_fn(rngoddess: bool, sources: list[str] | None, backend: str) -> DrawFn:
    if rngoddess:
        from .providers.mixer import RNGoddessMixer
        def draw(n, lane, tag):
            label = f"mcfa/v2/rngoddess/dataset/{tag}/" + (f"params/{lane}" if lane < 0 else f"lane/{lane:02d}")
            mixer = RNGoddessMixer(sources, label=label)
            data = mixer.read(n).data
            return data, {"provider": "rngoddess", "manifest": mixer.provenance()}
        return draw
    from .providers.eshkol import draw_from_drawd
    def draw(n, lane, tag):
        return draw_from_drawd(n, backend=backend), {"provider": f"eshkol-{backend}"}
    return draw


def _checked_draw(draw):
    def checked(n, lane, tag):
        # Bounded provider reads permit long pieces without a PRNG expansion.
        blocks, entries = [], []
        for offset in range(0, n, 65536):
            want = min(65536, n - offset)
            data, entry = draw(want, lane, tag if n <= 65536 else f"{tag}/block/{offset // 65536}")
            if len(data) != want:
                from .providers.base import EntropyProviderError
                raise EntropyProviderError(f"short entropy draw: {len(data)} bytes, expected {want}")
            blocks.append(data)
            entries.append(entry)
        return b"".join(blocks), entries[0] if len(entries) == 1 else {"blocks": entries}
    return checked


def _draw_info(data, entry):
    return {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(), **entry}


def _facts(data, index):
    """Recover only observable facts. Configured ranges/key/scale are intent."""
    import mido
    mid, stats = _parse(data), validate_midi(data)
    tempos, signature, total = [], "4/4", 0
    lanes = []
    for lane, track in enumerate(mid.tracks):
        tick, program, channel = 0, None, None
        for msg in track:
            tick += msg.time
            if msg.type == "set_tempo":
                tempos.append((tick, msg.tempo))
            if msg.type == "time_signature":
                signature = f"{msg.numerator}/{msg.denominator}"
            if msg.type == "program_change":
                program = msg.program
            if hasattr(msg, "channel"):
                channel = msg.channel
        total = max(total, tick)
        lanes.append({"lane": lane, "range": None, "channel": channel, "program": program})
    tempos.sort()
    if not tempos or tempos[0][0] > 0:
        tempos.insert(0, (0, 500000))
    bpms = [mido.tempo2bpm(t) for _, t in tempos]
    tempo = {"start": bpms[0]}
    if len(set(t for _, t in tempos)) > 1:
        tempo.update(min=min(bpms), max=max(bpms))
    num, den = map(int, signature.split("/"))
    bars = total / (mid.ticks_per_beat * num * 4 / den)
    return {"id": f"{index:06d}", "path": midi_path(index), "sha256": hashlib.sha256(data).hexdigest(),
            "recipe": None, "preset": None, "tempo": tempo, "key": None, "scale": None,
            "time_signature": signature, "lanes": lanes, "bars": int(bars) if bars.is_integer() else bars,
            "duration_s": stats["duration_s"], "note_count": stats["notes"]}


def _write_manifest(out, rows):
    atomic_write(out / "manifest.jsonl", "".join(json.dumps(rows[k], sort_keys=True) + "\n" for k in sorted(rows)).encode())


def _recover(out, schedule):
    saved = {}
    manifest = out / "manifest.jsonl"
    if manifest.exists():
        for line in manifest.read_text(errors="replace").splitlines():
            try:
                row = json.loads(line)
                if isinstance(row, dict) and MANIFEST_FIELDS <= row.keys():
                    saved[row["id"]] = row
            except (ValueError, KeyError, TypeError):
                continue
    rows, seen = {}, {}
    for path in sorted((out / "midi").rglob("*.mid")):
        if not path.stem.isdigit():
            raise ValueError(f"unexpected MIDI filename: {path}")
        index = int(path.stem)
        if path.relative_to(out).as_posix() != midi_path(index):
            raise ValueError(f"unsharded MIDI {path}; expected {midi_path(index)}")
        data = path.read_bytes()
        row = _facts(data, index)
        old = saved.get(row["id"])
        if old and old["sha256"] == row["sha256"] and old["path"] == row["path"]:
            for key in ("recipe", "preset", "key", "scale", "lanes"):
                row[key] = old[key]
        elif index < len(schedule):
            row["recipe"], row["preset"] = schedule[index][0:2]
        if row["sha256"] in seen:
            raise ValueError(f"existing duplicate MIDI: {row['id']} and {seen[row['sha256']]}")
        seen[row["sha256"]] = row["id"]
        rows[index] = row
    return rows, seen


class _Log:
    def __init__(self, path, out):
        self.path = Path(path).resolve() if path is not None else None
        if self.path and (self.path == out or out in self.path.parents):
            raise ValueError("log path must be outside the dataset directory")
        self.card = self.path.with_name(self.path.name + ".summary.md") if self.path else None
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, event):
        if self.path:
            # Recover a torn trailing log record before appending the next record.
            if self.path.exists():
                with self.path.open("rb+") as f:
                    data = f.read()
                    if data and not data.endswith(b"\n"):
                        f.truncate(data.rfind(b"\n") + 1)
            with self.path.open("ab") as f:
                f.write((json.dumps(event, sort_keys=True) + "\n").encode())
                f.flush()
                os.fsync(f.fileno())

    def summarize(self, summary, rows):
        if self.path:
            self.write({"event": "summary", **summary})
            tempos = [r["tempo"]["start"] for r in rows.values()]
            card = (f"# MCFA dataset generation log\n\n- Pieces: {summary['pieces']}\n"
                    f"- Distinct SHA256: {summary['distinct_sha256']}\n"
                    f"- Rejected this run: {summary['rejected']}\n"
                    f"- Recipes: {json.dumps(summary['recipes'], sort_keys=True)}\n"
                    f"\n## Musical controls\n\n- Tempo (BPM), starts: {min(tempos) if tempos else '-'} to {max(tempos) if tempos else '-'}\n")
            atomic_write(self.card, card.encode())


def generate_dataset(out_dir, count=None, *, lanes=4, bars=8, vary=False,
                     lanes_range=(1, 8), bars_range=(4, 16), controls=None, vary_spec=None,
                     legacy=False, rngoddess=True, sources=None, backend="moonlab", seed_label="piece",
                     resume=False, draw_fn=None, log=None, progress=None, recipes=None,
                     duration=None, tempo_changes=0, tempo_change_range=None, tempo_max_jump=None,
                     preset=None):
    from .midi_controls import MidiControls, VarySpec, vary_controls
    from .midi_timing import plan_timing
    from .recipes import Recipe, load_recipes, parse_recipes, recipe_controls

    out = Path(out_dir).resolve()
    # A callback remains supported as a progress sink for existing API clients.
    if callable(log):
        progress, log = log, None
    logger = _Log(log, out)
    base = (controls or MidiControls()).validate()
    if type(lanes) is not int or not 1 <= lanes <= 16 or type(bars) is not int or bars < 1:
        raise ValueError("lanes must be 1..16 and bars must be >= 1")
    if sources and not rngoddess:
        raise ValueError("sources require RNGoddess mode")
    spec = replace(vary_spec) if vary_spec else VarySpec()
    if vary:
        if spec.lanes_range is None:
            spec.lanes_range = lanes_range
        if spec.bars_range is None:
            spec.bars_range = bars_range
    spec.validate()
    if recipes is not None:
        if count is not None:
            raise ValueError("use recipe counts or count, not both")
        if legacy:
            raise ValueError("recipes require musical controls (no legacy)")
        recipe_list = load_recipes(recipes) if isinstance(recipes, (str, Path)) else recipes
        if not (isinstance(recipe_list, list) and all(isinstance(r, Recipe) for r in recipe_list)):
            recipe_list = parse_recipes(recipe_list)
    else:
        if type(count) is not int or count < 1:
            raise ValueError("count must be a positive integer")
        recipe_list = [Recipe(None, count, {}, spec if vary else VarySpec())]
    schedule = []
    for recipe in recipe_list:
        fixed = {"lanes": lanes, "bars": bars, "duration": duration, "tempo_changes": tempo_changes,
                 "tempo_change_range": tempo_change_range, "tempo_max_jump": tempo_max_jump, "preset": preset} | recipe.fixed
        ctl = recipe_controls(base, recipe.fixed)
        vs = recipe.vary.validate()
        if legacy and (fixed["duration"] is not None or fixed["tempo_changes"] or any(
                v is not None for k, v in asdict(vs).items() if k not in ("lanes_range", "bars_range"))):
            raise ValueError("legacy mode cannot use duration or musical variation")
        # Validate timing and fixed dimensions before writing any files/drawing entropy.
        if type(fixed["lanes"]) is not int or not 1 <= fixed["lanes"] <= 16 or type(fixed["bars"]) is not int or fixed["bars"] < 1:
            raise ValueError("invalid recipe lanes/bars")
        check_ctl = replace(ctl, tempo=sum(vs.tempo_range) / 2) if vs.tempo_range else ctl
        if type(fixed["tempo_changes"]) is not int or not 0 <= fixed["tempo_changes"] <= 1024:
            raise ValueError("tempo_changes must be an integer in 0..1024")
        plan_timing(check_ctl, max(fixed["bars"], fixed["tempo_changes"] + 1) if fixed["duration"] else fixed["bars"],
                    fixed["tempo_changes"], fixed["tempo_change_range"], fixed["tempo_max_jump"],
                    bytes(fixed["tempo_changes"] * 2), None if fixed["tempo_changes"] or any(v is not None for v in asdict(vs).values()) else fixed["duration"])
        schedule.extend([(recipe.name, fixed["preset"], fixed, ctl, vs)] * recipe.count)
    existing = (out / "manifest.jsonl").exists() or any((out / "midi").rglob("*.mid"))
    if existing and not resume:
        raise FileExistsError(f"{out} already has pieces; pass resume=True to continue")
    # Refuse old layout rather than deleting someone's previous provenance.
    if any((out / name).exists() for name in ("meta", "dataset_card.md", "rejects.jsonl")):
        raise ValueError("old dataset layout present; use a new output directory")
    if out.exists() and any(p.name not in ("midi", "manifest.jsonl") for p in out.iterdir()):
        raise ValueError("dataset directory contains files other than MIDI and manifest")
    rows, seen = _recover(out, schedule) if resume else ({}, {})
    for i, row in rows.items():
        if i < len(schedule) and row["recipe"] != schedule[i][0]:
            raise ValueError("recipe schedule differs from existing manifest")
    out.mkdir(parents=True, exist_ok=True)
    _write_manifest(out, rows)
    draw = _checked_draw(draw_fn or default_draw_fn(rngoddess, sources, backend))
    tool, commit = _load_tool(), git_commit()
    logger.write({"event": "run", "schema": SCHEMA, "generator_commit": commit,
                  "source": {"rngoddess": rngoddess, "sources": (sources or ["eshkol-local:moonlab"]) if rngoddess else [f"eshkol-local:{backend}"]},
                  "schedule": [{"name": r.name, "count": r.count, "fixed": r.fixed, "vary": asdict(r.vary)} for r in recipe_list]})
    made = skipped = rejected = 0
    try:
        for index, (name, piece_preset, fixed, ctl, vs) in enumerate(schedule):
            if index in rows:
                skipped += 1
                continue
            pid = f"{index:06d}"
            for attempt in range(1, MAX_ATTEMPTS + 1):
                tag = f"{seed_label}-{pid}" + (f"-r{attempt}" if attempt > 1 else "")
                piece_ctl, nlanes, nbars = ctl, fixed["lanes"], fixed["bars"]
                params = {"legacy": legacy, "vary": {}, "tempo_draw": None}
                if any(v is not None for v in asdict(vs).values()):
                    data0, entry0 = draw(32, -1, tag)
                    piece_ctl, nlanes, nbars, drawn = vary_controls(ctl, vs, data0, nlanes, nbars)
                    params["vary"] = {"drawn": drawn, **_draw_info(data0, entry0)}
                drawn = params["vary"].get("drawn", {})
                changes = drawn.get("tempo_changes", fixed["tempo_changes"])
                jump = drawn.get("tempo_max_jump", fixed["tempo_max_jump"])
                td = b""
                if changes:
                    td, te = draw(changes * 2, -2, tag)
                    params["tempo_draw"] = _draw_info(td, te)
                bounds = fixed["tempo_change_range"] or vs.tempo_range
                try:
                    nbars, timing = plan_timing(piece_ctl, nbars, changes, bounds, jump, td, fixed["duration"])
                except ValueError as exc:
                    # Entropy may produce an infeasible whole-bar duration; reject
                    # that attempt. Provider exceptions always propagate immediately.
                    if not (changes or any(v is not None for v in asdict(vs).values())):
                        raise
                    rejected += 1
                    logger.write({"event": "reject", "id": pid, "recipe": name, "preset": piece_preset,
                                  "attempt": attempt, "seed_label": tag, "reason": str(exc),
                                  "params": params | {"controls": piece_ctl.public(), "tempo_changes": changes,
                                                      "tempo_change_range": bounds, "tempo_max_jump": jump,
                                                      "duration_target": fixed["duration"]}, "generator_commit": commit})
                    if progress:
                        progress(f"reject {pid} attempt {attempt}: {exc}")
                    continue
                params.update(lanes=nlanes, bars=nbars, controls=None if legacy else piece_ctl.public(),
                              tempo_map=timing, duration_target=fixed["duration"], tempo_max_jump=jump)
                events = [(round(bar * piece_ctl.beats_per_bar * 480), tempo) for bar, tempo in timing]
                mid, prov = tool.generate_midi(nlanes, nbars, seed_tag=tag,
                    draw_fn=lambda n, lane: draw(n, lane, tag), controls=piece_ctl, legacy=legacy,
                    tempo_events=None if legacy else events)
                buf = io.BytesIO()
                mid.save(file=buf)
                data, reason = buf.getvalue(), None
                sha = hashlib.sha256(data).hexdigest()
                try:
                    stats = validate_midi(data)
                    if fixed["duration"] is not None and abs(stats["duration_s"] - fixed["duration"]) > 2:
                        raise ValueError("duration outside +/-2 s")
                except ValueError as exc:
                    reason = str(exc)
                if reason is None and sha in seen:
                    reason = f"duplicate of {seen[sha]}"
                record = {"id": pid, "recipe": name, "preset": piece_preset, "attempt": attempt,
                          "seed_label": tag, "sha256": sha, "params": params,
                          "lanes_provenance": prov["draws"], "lane_layout": prov.get("lane_layout", []),
                          "generator_commit": commit, "created_at": _dt.datetime.now(_dt.timezone.utc).isoformat()}
                if reason:
                    rejected += 1
                    logger.write({"event": "reject", "reason": reason, **record})
                    if progress:
                        progress(f"reject {pid} attempt {attempt}: {reason}")
                    continue
                break
            else:
                raise RuntimeError(f"piece {pid} rejected {MAX_ATTEMPTS} times")
            row = _facts(data, index)
            row.update(recipe=name, preset=piece_preset, key=None if legacy else piece_ctl.key,
                       scale=None if legacy else piece_ctl.scale,
                       lanes=prov["lane_layout"] if not legacy else row["lanes"])
            atomic_write(out / row["path"], data)
            rows[index], seen[sha] = row, pid
            _write_manifest(out, rows)
            logger.write({"event": "piece", "manifest": row, **record})
            made += 1
            if progress:
                progress(f"{pid}: {row['note_count']} notes, {row['duration_s']:.3f} s")
    except Exception as exc:
        logger.write({"event": "error", "error": str(exc), "generator_commit": commit})
        logger.summarize(finalize(out, rows) | {"made": made, "skipped": skipped, "rejected": rejected}, rows)
        raise
    summary = finalize(out, rows)
    summary.update(made=made, skipped=skipped, rejected=rejected)
    logger.summarize(summary, rows)
    return summary


def finalize(out, rows=None):
    out = Path(out)
    if rows is None:
        rows, _ = _recover(out, [])
    _write_manifest(out, rows)
    durations = [r["duration_s"] for r in rows.values()]
    return {"pieces": len(rows), "distinct_sha256": len({r["sha256"] for r in rows.values()}),
            "total_bytes": sum((out / r["path"]).stat().st_size for r in rows.values()),
            "duration_range": [min(durations), max(durations)] if durations else [None, None],
            "recipes": dict(Counter(r["recipe"] or "unlabelled" for r in rows.values()))}
