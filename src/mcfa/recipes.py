"""Validated YAML/JSON recipe schedules; labels never enter MIDI messages."""
from __future__ import annotations

from dataclasses import asdict, dataclass, fields
import json
from pathlib import Path

from .midi_controls import KEYS, SCALES, TIME_SIGNATURES, MidiControls, VarySpec

PARAMS = {f.name for f in fields(MidiControls)} | {
    "lanes", "bars", "duration", "tempo_changes", "tempo_change_range", "tempo_max_jump", "preset", "motion"}
ALL_CHOICES = {"keys": KEYS, "scales": sorted(SCALES), "time_signatures": TIME_SIGNATURES}


@dataclass
class Recipe:
    name: str
    count: int
    fixed: dict
    vary: VarySpec


def parse_recipes(document) -> list[Recipe]:
    if isinstance(document, dict):
        if set(document) != {"recipes"}:
            raise ValueError("recipe document must contain only 'recipes'")
        document = document["recipes"]
    if not isinstance(document, list) or not document:
        raise ValueError("recipes must be a nonempty list")
    result, names = [], set()
    for item in document:
        if not isinstance(item, dict) or set(item) - {"name", "count", "fixed", "vary"}:
            raise ValueError("recipe fields: name, count, fixed, vary")
        name, count = item.get("name"), item.get("count")
        if not isinstance(name, str) or not name.strip() or name in names:
            raise ValueError("recipe names must be nonempty and unique")
        if type(count) is not int or count < 1:
            raise ValueError("recipe count must be a positive integer")
        names.add(name)
        fixed, varying = item.get("fixed", {}), item.get("vary", {})
        if not isinstance(fixed, dict) or set(fixed) - PARAMS:
            raise ValueError(f"unknown fixed params for {name}")
        if not isinstance(varying, dict):
            raise ValueError("vary must be a mapping of VarySpec fields")
        varying = dict(varying)
        for field_name, choices in ALL_CHOICES.items():
            if varying.get(field_name) == "all":
                varying[field_name] = list(choices)
        if varying.get("program_choices") == "all":
            varying["program_choices"] = [[i] for i in range(128)]
        try:
            spec = VarySpec(**varying).validate()
            if "motion" in fixed:
                from .midi_motion import MotionControls
                MotionControls(**fixed["motion"]).validate()
            MidiControls(**{k: v for k, v in fixed.items() if k in {f.name for f in fields(MidiControls)}}).validate()
        except (TypeError, ValueError) as exc:
            raise ValueError(f"bad recipe {name}: {exc}") from exc
        result.append(Recipe(name, count, fixed, spec))
    return result


def load_recipes(path: str | Path) -> list[Recipe]:
    text = Path(path).read_text()
    try:
        document = json.loads(text)
    except json.JSONDecodeError:
        try:
            import yaml
        except ImportError as exc:
            raise ValueError("YAML recipes need PyYAML: pip install '.[dataset]'; JSON needs no YAML dependency") from exc
        document = yaml.safe_load(text)
    return parse_recipes(document)


def recipe_controls(base, fixed):
    control_fields = {f.name for f in fields(MidiControls)}
    return MidiControls(**(asdict(base) | {k: v for k, v in fixed.items() if k in control_fields})).validate()
