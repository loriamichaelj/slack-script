"""Turn raw daily costs into a summary: one day's spend against its recent average."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta

from ..models import CostData, CostSpec


@dataclass(frozen=True)
class CostSettings:
    lag_days: int = 1  # report on the day this many days ago; billing data arrives late
    baseline_days: int = 7
    alert_pct: float = 25.0
    min_abs_change: float = 1.0  # ignore percentage jumps on tiny bills
    top_services: int = 5


@dataclass(frozen=True)
class ServiceCost:
    service: str
    amount: float
    change_pct: float | None  # against the service's own baseline average


@dataclass
class CostSummary:
    spec: CostSpec
    provider: str
    scope: str
    currency: str
    day: date
    total: float | None  # None when the day has no data yet
    baseline: float | None  # average daily spend over the baseline days that have data
    month_to_date: float
    services: list[ServiceCost] = field(default_factory=list)
    spike: bool = False

    @property
    def change_pct(self) -> float | None:
        return _pct(self.total, self.baseline)


def report_day(today: date, settings: CostSettings) -> date:
    return today - timedelta(days=settings.lag_days)


def fetch_window(day: date, settings: CostSettings) -> tuple[date, date]:
    """Start and exclusive end covering the baseline days and the month to date."""
    start = min(day.replace(day=1), day - timedelta(days=settings.baseline_days))
    return start, day + timedelta(days=1)


def _pct(value: float | None, base: float | None) -> float | None:
    if value is None or not base:
        return None
    return (value - base) / base * 100


def summarize(spec: CostSpec, data: CostData, day: date, settings: CostSettings) -> CostSummary:
    by_day: dict[date, float] = defaultdict(float)
    by_service_day: dict[str, dict[date, float]] = defaultdict(lambda: defaultdict(float))
    for row in data.rows:
        by_day[row.day] += row.amount
        by_service_day[row.service][row.day] += row.amount

    baseline_days = [day - timedelta(days=i) for i in range(1, settings.baseline_days + 1)]
    seen = [d for d in baseline_days if d in by_day]
    baseline = sum(by_day[d] for d in seen) / len(seen) if seen else None
    total = by_day[day] if day in by_day else None
    month_to_date = sum(v for d, v in by_day.items() if d.replace(day=1) == day.replace(day=1) and d <= day)

    services = []
    for service, days in by_service_day.items():
        amount = days.get(day, 0.0)
        if amount <= 0:
            continue
        base = sum(days.get(d, 0.0) for d in seen) / len(seen) if seen else None
        services.append(ServiceCost(service, amount, _pct(amount, base)))
    services.sort(key=lambda s: (-s.amount, s.service))

    summary = CostSummary(
        spec=spec,
        provider=data.provider,
        scope=data.scope,
        currency=data.currency,
        day=day,
        total=total,
        baseline=baseline,
        month_to_date=month_to_date,
        services=services[: settings.top_services],
    )
    change = summary.change_pct
    summary.spike = (
        change is not None
        and change >= settings.alert_pct
        and total - baseline >= settings.min_abs_change
    )
    return summary
