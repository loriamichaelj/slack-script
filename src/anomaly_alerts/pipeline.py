"""One run: fetch, detect, dedup, enrich, post. Cloud-agnostic from the Series onward."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Callable

from . import actions
from .config import Config
from .detectors.guards import evaluate
from .models import SEVERITY_RANK, Anomaly, MetricSpec, Point, Series
from .providers import ProviderPool
from .slack import blocks
from .slack.client import SlackError
from .state import StateStore

log = logging.getLogger(__name__)

RECENT_POINTS = 12


@dataclass
class RunResult:
    fetched: int = 0
    fetch_errors: int = 0
    anomalies: int = 0
    in_cooldown: int = 0
    over_limit: int = 0
    posted: int = 0
    post_errors: int = 0

    @property
    def ok(self) -> bool:
        return self.fetch_errors == 0 and self.post_errors == 0


def floor_ts(dt: datetime, period_seconds: int) -> datetime:
    epoch = dt.timestamp()
    return datetime.fromtimestamp(epoch - epoch % period_seconds, UTC)


def clean_points(points: list[Point], spec: MetricSpec, start: datetime, now: datetime) -> list[Point]:
    """Drop incomplete and out-of-range periods, de-duplicate, and optionally zero-fill gaps."""
    period = timedelta(seconds=spec.period_seconds)
    by_ts: dict[datetime, float] = {}
    for p in points:
        ts = floor_ts(p.ts, spec.period_seconds)
        if ts >= start and ts + period <= now:  # the newest period may still be filling in
            by_ts[ts] = p.value

    if spec.fill_missing == "zero":
        last = floor_ts(now, spec.period_seconds) - period
        count = int((last - start) / period) + 1
        return [Point(start + i * period, by_ts.get(start + i * period, 0.0)) for i in range(count)]
    return [Point(ts, by_ts[ts]) for ts in sorted(by_ts)]


def _detect(spec: MetricSpec, series: Series, start: datetime, now: datetime) -> Anomaly | None:
    points = clean_points(series.points, spec, start, now)
    expected = int((floor_ts(now, spec.period_seconds) - start) / timedelta(seconds=spec.period_seconds))
    if spec.fill_missing == "drop" and expected and len(points) < expected / 2:
        log.warning(
            "%s: data gap, only %d of about %d expected points (set fill_missing: zero "
            "if a missing period means zero)", spec.name, len(points), expected
        )
    detection = evaluate([p.value for p in points], spec)
    if detection is None:
        return None
    window = points[-spec.sustained_points:]
    return Anomaly(
        spec=spec,
        series=series,
        detection=detection,
        window_start=window[0].ts,
        window_end=window[-1].ts + timedelta(seconds=spec.period_seconds),
        recent=[p.value for p in points[-RECENT_POINTS:]],
    )


def run(
    config: Config,
    pool: ProviderPool,
    rules: list[actions.Rule],
    state: StateStore,
    post: Callable[[dict], None],
    now: datetime | None = None,
    *,
    dry_run: bool = False,
    only: str | None = None,
) -> RunResult:
    now = now or datetime.now(UTC)
    result = RunResult()
    found: list[Anomaly] = []

    for spec in config.metrics:
        if only and spec.provider != only:
            continue
        start = floor_ts(now - timedelta(seconds=spec.lookback_seconds), spec.period_seconds)
        try:
            series = pool.get(spec.provider).fetch(spec, start, now)
        except Exception as exc:  # one bad metric must not stop the others
            log.error("%s: fetch failed: %s: %s", spec.name, type(exc).__name__, exc)
            result.fetch_errors += 1
            continue
        result.fetched += 1
        log.debug("%s: fetched %d points", spec.name, len(series.points))
        anomaly = _detect(spec, series, start, now)
        if anomaly:
            found.append(anomaly)
    result.anomalies = len(found)

    fresh = []
    for anomaly in found:
        if state.allow(anomaly.fingerprint, anomaly.severity, now):
            fresh.append(anomaly)
        else:
            result.in_cooldown += 1
    fresh.sort(key=lambda a: (-SEVERITY_RANK[a.severity], -abs(a.detection.score)))

    cap = config.slack.max_alerts_per_run
    to_send, held_back = fresh[:cap], fresh[cap:]
    result.over_limit = len(held_back)

    for anomaly in to_send:
        try:
            post(blocks.build_payload(anomaly, actions.steps_for(anomaly, rules)))
        except SlackError as exc:
            log.error("%s: could not post alert: %s", anomaly.spec.name, exc)
            result.post_errors += 1
            continue
        result.posted += 1
        if not dry_run:
            state.record(anomaly.fingerprint, anomaly.severity, now)

    if held_back:
        try:
            post(blocks.build_overflow_payload(len(held_back), cap))
        except SlackError as exc:
            log.error("could not post the suppressed-alerts notice: %s", exc)
            result.post_errors += 1

    if not dry_run:
        state.save(now)
    return result
