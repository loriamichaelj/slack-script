"""Routine reports: scheduled summaries that post whether or not anything is wrong."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Callable

from . import pipeline
from .config import Config
from .providers import ProviderPool
from .slack import blocks
from .slack.client import SlackError

log = logging.getLogger(__name__)

KINDS = ("heartbeat",)


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
    result = RoutineResult(
        checked=len(outcomes) - len(failed),
        total=len(outcomes),
        anomalies=sum(1 for o in outcomes if o.anomaly),
        fetch_errors=len(failed),
    )
    payload = blocks.build_heartbeat_payload(
        now,
        checked=result.checked,
        total=result.total,
        anomalies=result.anomalies,
        failed=failed,
    )
    try:
        post(payload)
    except SlackError as exc:
        log.error("could not post the heartbeat: %s", exc)
        result.post_errors += 1
    else:
        result.posted += 1
    return result


def run(kind: str, *args, **kwargs) -> RoutineResult:
    if kind == "heartbeat":
        return run_heartbeat(*args, **kwargs)
    raise ValueError(f"unknown routine kind {kind!r}; expected one of {KINDS}")
