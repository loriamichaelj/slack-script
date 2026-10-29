"""Routine reports: scheduled summaries that post whether or not anything is wrong."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Callable

from . import pipeline
from .config import Config
from .cost import CostProviderPool
from .cost import report as cost_report
from .detectors import DETECTORS
from .models import SEVERITY_RANK, series_name
from .providers import ProviderPool
from .slack import blocks
from .slack.client import SlackError
from .state import StateStore

log = logging.getLogger(__name__)

KINDS = ("heartbeat", "digest", "cost")

# Digest row statuses, worst first. The order is also the sort order in the message.
CRITICAL, WARNING, FAILED, LEARNING, OK = "critical", "warning", "failed", "learning", "ok"
STATUS_ORDER = (CRITICAL, WARNING, FAILED, LEARNING, OK)


@dataclass
class RoutineResult:
    checked: int = 0
    total: int = 0
    anomalies: int = 0
    fetch_errors: int = 0
    posted: int = 0
    post_errors: int = 0

    @property
    def ok(self) -> bool:
        # A fetch error is reported in the message itself; only a failed post is a failed run.
        return self.post_errors == 0


def run_heartbeat(
    config: Config,
    pool: ProviderPool,
    post: Callable[[dict], None],
    now: datetime | None = None,
    *,
    only: str | None = None,
) -> RoutineResult:
    now = now or datetime.now(UTC)
    outcomes = pipeline.scan(config, pool, now, only)
    failed = [o.spec.name for o in outcomes if o.series is None]
    flagged = sorted(
        (
            (series_name(o.spec, o.series), o.spec.provider, o.anomaly.severity)
            for o in outcomes
            if o.anomaly
        ),
        key=lambda f: (-SEVERITY_RANK[f[2]], f[0]),
    )
    clouds: dict[str, list[int]] = {}
    for o in outcomes:
        counts = clouds.setdefault(o.spec.provider, [0, 0])
        counts[0] += o.series is not None
        counts[1] += 1

    # The alert job saves the state file on every run, so it shows that job is alive too.
    state = StateStore(config.state_path, config.slack.cooldown_seconds)
    state.load()

    result = RoutineResult(
        checked=len(outcomes) - len(failed),
        total=len(outcomes),
        anomalies=len(flagged),
        fetch_errors=len(failed),
    )
    payload = blocks.build_heartbeat_payload(
        now,
        checked=result.checked,
        total=result.total,
        flagged=flagged,
        failed=failed,
        clouds={p: tuple(c) for p, c in sorted(clouds.items())},
        last_alert_run=state.last_saved(),
        alerted_24h=state.alerted_since(now - timedelta(hours=24)),
    )
    _post(post, payload, result, "heartbeat")
    return result


@dataclass(frozen=True)
class DigestRow:
    """One metric's line in the health digest."""

    name: str
    provider: str
    status: str
    unit: str = ""
    latest: float | None = None
    center: float | None = None
    center_label: str = ""
    points: int = 0
    needed: int = 0  # points required before the metric has a baseline
    recent: tuple[float, ...] = ()


def _row(outcome: pipeline.MetricOutcome) -> DigestRow:
    spec, series, values = outcome.spec, outcome.series, outcome.values
    if series is None:
        return DigestRow(spec.name, spec.provider, FAILED)
    common = dict(
        name=series_name(spec, series),
        provider=spec.provider,
        unit=series.unit,
        points=len(values),
        needed=spec.min_points + spec.sustained_points,
        recent=tuple(values[-pipeline.RECENT_POINTS:]),
        center_label=DETECTORS[spec.detector].CENTER_LABEL,
    )
    if outcome.anomaly:
        det = outcome.anomaly.detection
        return DigestRow(status=det.severity, latest=det.observed, center=det.center, **common)
    if len(values) < common["needed"]:
        return DigestRow(status=LEARNING, latest=values[-1] if values else None, **common)
    k = spec.sustained_points
    scored = DETECTORS[spec.detector].score(values[:-k], values[-k:], alpha=spec.alpha)
    return DigestRow(status=OK, latest=values[-1], center=scored.center, **common)


def run_digest(
    config: Config,
    pool: ProviderPool,
    post: Callable[[dict], None],
    now: datetime | None = None,
    *,
    only: str | None = None,
) -> RoutineResult:
    now = now or datetime.now(UTC)
    outcomes = pipeline.scan(config, pool, now, only)
    rows = sorted((_row(o) for o in outcomes), key=lambda r: (STATUS_ORDER.index(r.status), r.name))
    failed = sum(1 for r in rows if r.status == FAILED)
    result = RoutineResult(
        checked=len(rows) - failed,
        total=len(rows),
        anomalies=sum(1 for r in rows if r.status in (CRITICAL, WARNING)),
        fetch_errors=failed,
    )
    _post(post, blocks.build_digest_payload(now, rows), result, "health digest")
    return result


def run_cost(
    config: Config,
    pool: CostProviderPool,
    post: Callable[[dict], None],
    now: datetime | None = None,
    *,
    only: str | None = None,
) -> RoutineResult:
    """Yesterday's spend per account against its recent average. Needs a cost section."""
    if config.cost is None:
        raise ValueError("the cost report needs a cost section in the config")
    now = now or datetime.now(UTC)
    settings = config.cost.settings
    day = cost_report.report_day(now.date(), settings)
    start, end = cost_report.fetch_window(day, settings)

    summaries, failed = [], []
    for spec in config.cost.accounts:
        if only and spec.provider != only:
            continue
        try:
            data = pool.get(spec.provider).fetch(spec, start, end)
        except Exception as exc:  # one bad account must not stop the others
            log.error("%s: cost fetch failed: %s: %s", spec.name, type(exc).__name__, exc)
            failed.append(spec)
            continue
        summaries.append(cost_report.summarize(spec, data, day, settings))

    result = RoutineResult(
        checked=len(summaries),
        total=len(summaries) + len(failed),
        anomalies=sum(1 for s in summaries if s.spike),
        fetch_errors=len(failed),
    )
    _post(post, blocks.build_cost_payload(now, day, summaries, failed), result, "cost report")
    return result


def _post(post: Callable[[dict], None], payload: dict, result: RoutineResult, label: str) -> None:
    try:
        post(payload)
    except SlackError as exc:
        log.error("could not post the %s: %s", label, exc)
        result.post_errors += 1
    else:
        result.posted += 1


_RUNNERS = {"heartbeat": run_heartbeat, "digest": run_digest, "cost": run_cost}


def run(kind: str, *args, **kwargs) -> RoutineResult:
    if kind not in _RUNNERS:
        raise ValueError(f"unknown routine kind {kind!r}; expected one of {KINDS}")
    return _RUNNERS[kind](*args, **kwargs)
