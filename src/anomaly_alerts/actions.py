"""Recommended actions from a YAML rule table. First matching rule wins."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from .config import ConfigError
from .models import Anomaly

GENERIC_STEPS = [
    "Open the console link and compare the last 24 hours",
    "Check for a recent deploy or configuration change on this resource",
]

_MATCH_KEYS = {"category", "direction", "provider"}


@dataclass(frozen=True)
class Rule:
    match: dict
    steps: list[str]


def load_rules(path: Path | None) -> list[Rule]:
    if path is None:
        return []
    try:
        raw = yaml.safe_load(path.read_text())
    except OSError as exc:
        raise ConfigError(f"cannot read actions file {path}: {exc.strerror}") from exc
    except yaml.YAMLError as exc:
        raise ConfigError(f"{path} is not valid YAML: {exc}") from exc

    entries = raw.get("actions") if isinstance(raw, dict) else None
    if not isinstance(entries, list):
        raise ConfigError(f"{path}: expected a top-level 'actions' list")
    rules = []
    for i, entry in enumerate(entries):
        label = f"{path.name} actions[{i}]"
        match = entry.get("match") if isinstance(entry, dict) else None
        steps = entry.get("steps") if isinstance(entry, dict) else None
        if not isinstance(match, dict) or not match:
            raise ConfigError(f"{label}: match must be a non-empty mapping")
        if set(match) - _MATCH_KEYS:
            raise ConfigError(f"{label}: match keys must be from {sorted(_MATCH_KEYS)}")
        if not isinstance(steps, list) or not steps or not all(isinstance(s, str) for s in steps):
            raise ConfigError(
                f"{label}: steps must be a non-empty list of strings "
                "(quote any step that contains a colon)"
            )
        rules.append(Rule(match=match, steps=steps))
    return rules


def steps_for(anomaly: Anomaly, rules: list[Rule]) -> list[str]:
    facts = {
        "category": anomaly.spec.category,
        "direction": anomaly.direction,
        "provider": anomaly.series.provider,
    }
    for rule in rules:
        if all(facts[k] == v for k, v in rule.match.items()):
            return list(rule.steps)
    return list(GENERIC_STEPS)
