"""Load and validate the YAML config. Every error names the entry it came from."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import yaml

from .detectors import DETECTORS
from .models import BOTH, DROP, SPIKE, MetricSpec


class ConfigError(Exception):
    pass


_TOP_KEYS = {"slack", "state", "actions_file", "defaults", "metrics"}
_SLACK_KEYS = {"webhook_env", "cooldown_minutes", "max_alerts_per_run"}

# Keys that belong to MetricSpec itself; everything else on a metric is a cloud selector.
_TUNING_KEYS = {
    "category", "direction", "lookback", "period", "detector", "threshold",
    "min_points", "sustained_points", "min_abs_change", "alpha", "fill_missing", "runbook",
}
_METRIC_KEYS = _TUNING_KEYS | {"name", "provider"}

_SELECTORS = {
    "aws": ({"region", "namespace", "metric"}, {"dimensions", "stat"}),
    "azure": ({"resource_id", "metric"}, {"aggregation", "namespace"}),
    "gcp": ({"project", "metric_type"}, {"filter", "aligner", "reducer"}),
}

_DURATION = re.compile(r"^(\d+)\s*([smhd])$")
_UNIT_SECONDS = {"s": 1, "m": 60, "h": 3600, "d": 86400}


@dataclass(frozen=True)
class SlackConfig:
    webhook_env: str = "SLACK_WEBHOOK_URL"
    cooldown_seconds: int = 3600
    max_alerts_per_run: int = 10


@dataclass(frozen=True)
class Config:
    slack: SlackConfig
    state_path: Path
    actions_path: Path | None
    metrics: list[MetricSpec]


def parse_duration(value, label: str) -> int:
    match = _DURATION.match(str(value).strip().lower())
    if not match or int(match[1]) == 0:
        raise ConfigError(f"{label}: expected a duration like 30s, 5m, 24h or 7d, got {value!r}")
    return int(match[1]) * _UNIT_SECONDS[match[2]]


def _number(source: dict, key: str, default, label: str, *, integer=False, minimum=None, maximum=None):
    raw = source.get(key, default)
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise ConfigError(f"{label}: {key} must be a number, got {raw!r}")
    if integer and raw != int(raw):
        raise ConfigError(f"{label}: {key} must be a whole number, got {raw!r}")
    value = int(raw) if integer else float(raw)
    if minimum is not None and value < minimum:
        raise ConfigError(f"{label}: {key} must be at least {minimum}, got {value}")
    if maximum is not None and value > maximum:
        raise ConfigError(f"{label}: {key} must be at most {maximum}, got {value}")
    return value


def _choice(source: dict, key: str, default, options, label: str) -> str:
    value = source.get(key, default)
    if value not in options:
        raise ConfigError(f"{label}: {key} must be one of {sorted(options)}, got {value!r}")
    return value


def _build_spec(entry, defaults: dict, index: int) -> MetricSpec:
    if not isinstance(entry, dict):
        raise ConfigError(f"metrics[{index}]: must be a mapping")
    name = entry.get("name")
    if not name or not isinstance(name, str):
        raise ConfigError(f"metrics[{index}]: name is required")
    label = f"metric {name!r}"

    provider = entry.get("provider")
    if provider not in _SELECTORS:
        raise ConfigError(f"{label}: provider must be one of {sorted(_SELECTORS)}, got {provider!r}")
    required, optional = _SELECTORS[provider]
    selector = {k: v for k, v in entry.items() if k not in _METRIC_KEYS}
    unknown = set(selector) - required - optional
    if unknown:
        raise ConfigError(f"{label}: unknown key(s) {sorted(unknown)} for provider {provider}")
    missing = required - set(selector)
    if missing:
        raise ConfigError(f"{label}: missing required key(s) {sorted(missing)} for provider {provider}")

    merged = {**defaults, **{k: v for k, v in entry.items() if k in _TUNING_KEYS}}
    detector = _choice(merged, "detector", "mad", DETECTORS, label)
    threshold = _number(
        merged, "threshold", DETECTORS[detector].DEFAULT_THRESHOLD, label, minimum=0.1
    )
    lookback = parse_duration(merged.get("lookback", "24h"), f"{label}: lookback")
    period = parse_duration(merged.get("period", "5m"), f"{label}: period")
    min_points = _number(merged, "min_points", 30, label, integer=True, minimum=5)
    sustained = _number(merged, "sustained_points", 3, label, integer=True, minimum=1)
    if lookback // period < min_points + sustained:
        raise ConfigError(
            f"{label}: lookback {lookback}s at period {period}s gives {lookback // period} points, "
            f"but min_points + sustained_points needs {min_points + sustained}"
        )
    runbook = merged.get("runbook")
    if runbook is not None and urlparse(str(runbook)).scheme not in ("http", "https"):
        raise ConfigError(f"{label}: runbook must be an http(s) URL, got {runbook!r}")

    return MetricSpec(
        name=name,
        provider=provider,
        selector=selector,
        category=str(merged.get("category", "generic")),
        direction=_choice(merged, "direction", BOTH, {SPIKE, DROP, BOTH}, label),
        lookback_seconds=lookback,
        period_seconds=period,
        detector=detector,
        threshold=threshold,
        min_points=min_points,
        sustained_points=sustained,
        min_abs_change=_number(merged, "min_abs_change", 0.0, label, minimum=0),
        alpha=_number(merged, "alpha", 0.3, label, minimum=0.01, maximum=1),
        fill_missing=_choice(merged, "fill_missing", "drop", {"drop", "zero"}, label),
        runbook=runbook,
    )


def load(path: str | Path) -> Config:
    path = Path(path)
    try:
        raw = yaml.safe_load(path.read_text())
    except OSError as exc:
        raise ConfigError(f"cannot read {path}: {exc.strerror}") from exc
    except yaml.YAMLError as exc:
        raise ConfigError(f"{path} is not valid YAML: {exc}") from exc
    if not isinstance(raw, dict):
        raise ConfigError(f"{path}: top level must be a mapping")
    unknown = set(raw) - _TOP_KEYS
    if unknown:
        raise ConfigError(f"unknown top-level key(s) {sorted(unknown)}")

    slack_raw = raw.get("slack") or {}
    unknown = set(slack_raw) - _SLACK_KEYS
    if unknown:
        raise ConfigError(f"slack: unknown key(s) {sorted(unknown)}")
    slack = SlackConfig(
        webhook_env=str(slack_raw.get("webhook_env", "SLACK_WEBHOOK_URL")),
        cooldown_seconds=int(_number(slack_raw, "cooldown_minutes", 60, "slack", minimum=0) * 60),
        max_alerts_per_run=_number(slack_raw, "max_alerts_per_run", 10, "slack", integer=True, minimum=1),
    )

    defaults = raw.get("defaults") or {}
    bad = set(defaults) - _TUNING_KEYS
    if bad:
        raise ConfigError(f"defaults: unknown key(s) {sorted(bad)}")

    entries = raw.get("metrics")
    if not isinstance(entries, list) or not entries:
        raise ConfigError("metrics: at least one metric is required")
    metrics = [_build_spec(e, defaults, i) for i, e in enumerate(entries)]
    names = [m.name for m in metrics]
    dupes = sorted({n for n in names if names.count(n) > 1})
    if dupes:
        raise ConfigError(f"metrics: duplicate name(s) {dupes}")

    actions_file = raw.get("actions_file")
    return Config(
        slack=slack,
        state_path=Path((raw.get("state") or {}).get("path", ".state/alerts.json")),
        actions_path=(path.parent / actions_file) if actions_file else None,
        metrics=metrics,
    )
