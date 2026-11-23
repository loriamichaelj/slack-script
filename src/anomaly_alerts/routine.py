"""Routine reports: scheduled summaries that post whether or not anything is wrong."""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Callable

from . import pipeline
from .config import Config
from .cost import CostProviderPool
from .cost import report as cost_report
from .detectors import DETECTORS, needs_baseline
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


def _alert_state(config: Config, only: str | None) -> dict:
    """The state to read for each alert job. With no alert_state it is the one state_path,
    which has no cloud name because the config could not say which cloud wrote it."""
    if not config.alert_state:
        return {None: config.state_path}
    return {p: loc for p, loc in sorted(config.alert_state.items()) if not only or p == only}


Publish = Callable[[blocks.Report, datetime], None]


def run_heartbeat(
    config: Config,
    pool: ProviderPool,
    post: Callable[[dict], None],
    now: datetime | None = None,
    *,
    only: str | None = None,
    publish: Publish | None = None,
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

    # Each alert job saves its state file on every run, so the file shows that job is alive too.
    alert_jobs = {}
    for provider, location in _alert_state(config, only).items():
        state = StateStore(location, config.slack.cooldown_seconds)
        state.load()
        alert_jobs[provider] = (state.last_saved(), state.alerted_since(now - timedelta(hours=24)))

    result = RoutineResult(
        checked=len(outcomes) - len(failed),
        total=len(outcomes),
        anomalies=len(flagged),
        fetch_errors=len(failed),
    )
    report = blocks.build_heartbeat_report(
        now,
        checked=result.checked,
        total=result.total,
        flagged=flagged,
        failed=failed,
        clouds={p: tuple(c) for p, c in sorted(clouds.items())},
        alert_jobs=alert_jobs,
    )
    _post(post, report, now, result, "heartbeat", publish)
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
    fixed_limit: bool = False  # compared to a set limit, not a learned baseline


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
        fixed_limit=not needs_baseline(spec.detector),
    )
    if outcome.anomaly:
        det = outcome.anomaly.detection
        return DigestRow(status=det.severity, latest=det.observed, center=det.center, **common)
    if len(values) < common["needed"]:
        return DigestRow(status=LEARNING, latest=values[-1] if values else None, **common)
    if not needs_baseline(spec.detector):
        return DigestRow(status=OK, latest=values[-1], center=spec.threshold, **common)
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
    publish: Publish | None = None,
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
    _post(post, blocks.build_digest_report(rows), now, result, "health digest", publish)
    return result


def run_cost(
    config: Config,
    pool: CostProviderPool,
    post: Callable[[dict], None],
    now: datetime | None = None,
    *,
    only: str | None = None,
    publish: Publish | None = None,
) -> RoutineResult:
    """Yesterday's spend per account against its recent average. Needs a cost section."""
    if config.cost is None:
        raise ValueError("the cost report needs a cost section in the config")
    now = now or datetime.now(UTC)

    summaries, failed = [], []
    for spec in config.cost.accounts:
        if only and spec.provider != only:
            continue
        # Billing data lands later on some clouds, so an account can have its own lag.
        settings = config.cost.settings
        if spec.lag_days is not None:
            settings = replace(settings, lag_days=spec.lag_days)
        day = cost_report.report_day(now.date(), settings)
        start, end = cost_report.fetch_window(day, settings)
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
        anomalies=sum(1 for s in summaries if s.flagged),
        fetch_errors=len(failed),
    )
    _post(post, blocks.build_cost_report(summaries, failed), now, result, "cost report", publish)
    return result


def _post(
    post: Callable[[dict], None],
    report: blocks.Report,
    now: datetime,
    result: RoutineResult,
    label: str,
    publish: Publish | None = None,
) -> None:
    """Post the report to the shared message when there is one, else (or if that fails, so the
    report is not lost) to the webhook as this cloud's own message."""
    try:
        if publish is not None:
            try:
                publish(report, now)
            except SlackError as exc:
                log.error("could not update the shared %s, posting it on its own: %s", label, exc)
                post(report.payload(now))
        else:
            post(report.payload(now))
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
