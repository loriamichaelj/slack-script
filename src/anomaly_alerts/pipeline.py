"""One run: fetch, detect, dedup, enrich, post. Cloud-agnostic from the Series onward."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Callable

from . import actions
from .config import Config
from .detectors.guards import evaluate
from .models import SEVERITY_RANK, Anomaly, MetricSpec, Point, Series, series_name
from .providers import ProviderPool
from .slack import blocks
from .slack.client import SlackError
from .slack.threads import (
    RESOLVE_AFTER,
    AlertThreads,
    escalated,
    group_payload,
    resolved_line,
    summary_line,
)
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
    resolved: int = 0

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


def _detect(
    spec: MetricSpec, series: Series, points: list[Point], start: datetime, now: datetime
) -> Anomaly | None:
    expected = int((floor_ts(now, spec.period_seconds) - start) / timedelta(seconds=spec.period_seconds))
    if spec.fill_missing == "drop" and expected and len(points) < expected / 2:
        log.warning(
            "%s: data gap, only %d of about %d expected points (set fill_missing: zero "
            "if a missing period means zero)", series_name(spec, series), len(points), expected
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


@dataclass
class MetricOutcome:
    """What one metric produced in a scan: a series (and maybe an anomaly), or an error."""

    spec: MetricSpec
    series: Series | None = None
    anomaly: Anomaly | None = None
    error: str | None = None
    values: list[float] = field(default_factory=list)  # cleaned, oldest first


def scan(
    config: Config, pool: ProviderPool, now: datetime, only: str | None = None
) -> list[MetricOutcome]:
    """Fetch and test every configured metric. Shared by anomaly runs and routine reports."""
    outcomes = []
    for spec in config.metrics:
        if only and spec.provider != only:
            continue
        start = floor_ts(now - timedelta(seconds=spec.lookback_seconds), spec.period_seconds)
        try:
            fetched = pool.get(spec.provider).fetch(spec, start, now)
        except Exception as exc:  # one bad metric must not stop the others
            log.error("%s: fetch failed: %s: %s", spec.name, type(exc).__name__, exc)
            outcomes.append(MetricOutcome(spec, error=f"{type(exc).__name__}: {exc}"))
            continue
        # A metric split by group_by comes back as several series, each tested on its own.
        for series in fetched if isinstance(fetched, list) else [fetched]:
            log.debug("%s: fetched %d points", series_name(spec, series), len(series.points))
            points = clean_points(series.points, spec, start, now)
            outcomes.append(
                MetricOutcome(
                    spec,
                    series=series,
                    anomaly=_detect(spec, series, points, start, now),
                    values=[p.value for p in points],
                )
            )
    return outcomes


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
    threads: AlertThreads | None = None,
) -> RunResult:
    """One alert pass. With threads (the bot token), each alert is a thread that is followed up
    and resolved; without, each alert is a new webhook message."""
    now = now or datetime.now(UTC)
    result = RunResult()
    found: list[Anomaly] = []
    scanned: set[str] = set()  # series fetched this run, by fingerprint without the direction

    for outcome in scan(config, pool, now, only):
        if outcome.series is None:
            result.fetch_errors += 1
            continue
        result.fetched += 1
        s = outcome.series
        scanned.add("|".join((s.provider, s.scope, s.resource, s.metric)))
        if outcome.anomaly:
            found.append(outcome.anomaly)
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

    firing = {a.fingerprint for a in found}
    for anomaly in found:
        state.still_firing(anomaly.fingerprint)  # an open thread stays open while it fires

    threaded = threads is not None and not dry_run
    payloads = {a.fingerprint: blocks.build_payload(a, actions.steps_for(a, rules)) for a in to_send}
    # New alerts that fire together usually share a cause, so two or more go out as one group.
    new = [a for a in to_send if threaded and state.thread(a.fingerprint) is None]
    grouped = new if len(new) >= 2 else []
    sent = _send_group(threads, state, grouped, payloads, post, now) if grouped else {}

    for anomaly in to_send:
        payload = payloads[anomaly.fingerprint]
        name = series_name(anomaly.spec, anomaly.series)
        try:
            if anomaly in grouped:
                if not sent[anomaly.fingerprint]:  # sent above; a failure was logged there
                    raise SlackError("bot and webhook both failed")
            elif threaded:
                _send_threaded(threads, state, anomaly, payload, post, now)
            else:
                post(payload)
        except SlackError as exc:
            log.error("%s: could not post alert: %s", name, exc)
            result.post_errors += 1
            continue
        result.posted += 1
        if not dry_run:
            state.record(anomaly.fingerprint, anomaly.severity, now)

    if threads is not None and not dry_run:
        result.resolved = _resolve_quiet(threads, state, firing, scanned, now)

    if held_back:
        try:
            post(blocks.build_overflow_payload(len(held_back), cap))
        except SlackError as exc:
            log.error("could not post the suppressed-alerts notice: %s", exc)
            result.post_errors += 1

    if not dry_run:
        state.save(now)
    return result


def _send_threaded(
    threads: AlertThreads, state: StateStore, anomaly: Anomaly, payload: dict,
    post: Callable[[dict], None], now: datetime,
) -> None:
    """Open a thread, or follow up in the open one. If the bot fails, the webhook still alerts."""
    fp = anomaly.fingerprint
    open_thread = state.thread(fp)
    try:
        if open_thread is None:
            ts = threads.open(fp, payload)
            state.open_thread(fp, ts, payload, now)
        else:
            opened = datetime.fromisoformat(open_thread["opened"])
            was = open_thread.get("severity")
            group = open_thread.get("group")
            threads.follow_up(
                fp, open_thread["ts"], anomaly, payload, opened, now, escalated(was, anomaly.severity), group,
            )
            state.update_thread(fp, payload, line=summary_line(anomaly))
            if group:
                state.record(fp, anomaly.severity, now)  # the summary shows the new severity
                _refresh_group(threads, state, group)
    except SlackError as exc:
        log.warning("%s: bot post failed (%s); posting to the webhook instead",
                    series_name(anomaly.spec, anomaly.series), exc)
        post(payload)


def _send_group(
    threads: AlertThreads, state: StateStore, anomalies: list[Anomaly], payloads: dict[str, dict],
    post: Callable[[dict], None], now: datetime,
) -> dict[str, bool]:
    """A summary in the channel, then each alert's details in its thread. If the bot fails,
    each alert still goes to the webhook on its own. Returns whether each alert got out."""
    lines = {a.fingerprint: summary_line(a) for a in anomalies}
    members = [{"ts": "new", "line": lines[a.fingerprint], "severity": a.severity} for a in anomalies]
    sent: dict[str, bool] = {}

    def webhook(anomaly: Anomaly) -> bool:
        try:
            post(payloads[anomaly.fingerprint])
            return True
        except SlackError as exc:
            log.error("%s: could not post alert: %s", series_name(anomaly.spec, anomaly.series), exc)
            return False

    try:
        group = threads.open_group(group_payload(members))
    except SlackError as exc:
        log.warning("could not post the group summary (%s); posting each alert to the webhook", exc)
        return {a.fingerprint: webhook(a) for a in anomalies}
    for anomaly in anomalies:
        fp = anomaly.fingerprint
        try:
            ts = threads.add_to_group(group, payloads[fp])
        except SlackError as exc:
            log.warning("%s: could not add to its group (%s); posting to the webhook",
                        series_name(anomaly.spec, anomaly.series), exc)
            sent[fp] = webhook(anomaly)
            continue
        state.open_thread(fp, ts, payloads[fp], now, group=group, line=lines[fp])
        state.record(fp, anomaly.severity, now)
        sent[fp] = True
    return sent


def _refresh_group(threads: AlertThreads, state: StateStore, group: str) -> None:
    try:
        threads.update_group(group, group_payload(state.group_members(group)))
    except SlackError as exc:
        log.warning("could not update a group summary: %s", exc)


def _resolve_quiet(
    threads: AlertThreads, state: StateStore, firing: set[str], scanned: set[str], now: datetime
) -> int:
    """Close the threads whose metric was read this run and has been quiet long enough. A
    metric that could not be read says nothing either way, so its thread stays open."""
    resolved = 0
    for fp, entry in list(state.open_threads().items()):
        if fp in firing or fp.rsplit("|", 1)[0] not in scanned:
            continue
        if state.quiet_run(fp) < RESOLVE_AFTER:
            continue
        group = entry.get("group")
        try:
            opened = datetime.fromisoformat(entry["opened"])
            threads.resolve(fp, entry["ts"], entry.get("payload") or {}, opened, now, group)
        except (SlackError, KeyError, ValueError) as exc:
            log.warning("%s: could not mark resolved: %s", fp, exc)
            continue
        state.close_thread(fp, resolved_line(entry.get("line", ""), opened, now) if group else None)
        if group:
            _refresh_group(threads, state, group)
        resolved += 1
    return resolved
