"""Build Slack Block Kit payloads. Pure functions: no network, easy to test."""

from __future__ import annotations

from ..detectors import DETECTORS
from ..models import CRITICAL, SPIKE, Anomaly

COLORS = {"critical": "#d1242f", "warning": "#d4a72c", "ok": "#2da44e"}
PROVIDER_LABELS = {"aws": "AWS", "azure": "Azure", "gcp": "GCP"}
_BARS = "▁▂▃▄▅▆▇█"


def esc(text: str) -> str:
    """Escape the three characters Slack treats as control characters in mrkdwn."""
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def fmt(value: float) -> str:
    if value == 0:
        return "0"
    magnitude = abs(value)
    if magnitude >= 1000:
        return f"{value:,.0f}"
    text = f"{value:.2f}" if magnitude >= 1 else f"{value:.3g}"
    return text.rstrip("0").rstrip(".") if "." in text else text


def sparkline(values: list[float]) -> str:
    if not values:
        return ""
    lo, hi = min(values), max(values)
    if hi == lo:
        return _BARS[0] * len(values)
    return "".join(_BARS[min(7, int((v - lo) / (hi - lo) * 8))] for v in values)


def _stamp(dt) -> str:
    return dt.strftime("%Y-%m-%d %H:%M")


def build_payload(anomaly: Anomaly, steps: list[str]) -> dict:
    det, spec, series = anomaly.detection, anomaly.spec, anomaly.series
    module = DETECTORS[spec.detector]
    provider = PROVIDER_LABELS.get(series.provider, series.provider)
    severity = anomaly.severity.upper()
    arrow = "↑" if det.direction == SPIKE else "↓"
    unit = f" {esc(series.unit)}" if series.unit else ""

    title = f"*[{severity}]* {provider} | {esc(spec.name)} | {esc(series.metric)}"
    numbers = (
        f"{arrow} Observed *{fmt(det.observed)}{unit}* vs baseline {module.CENTER_LABEL} "
        f"*{fmt(det.center)}* ({module.SCORE_LABEL} = {det.score:+.1f}, "
        f"{det.breaching} consecutive points)"
    )
    context = (
        f"Window: {_stamp(anomaly.window_start)} to {_stamp(anomaly.window_end)} UTC"
        f" | Scope: {esc(series.scope)} | Resource: {esc(series.resource)}"
        f" | Detector: {spec.detector}"
    )
    recommendation = "*Recommended actions*\n" + "\n".join(
        f"{i}. {esc(step)}" for i, step in enumerate(steps, 1)
    )

    blocks = [
        {"type": "section", "text": {"type": "mrkdwn", "text": title}},
        {"type": "section", "text": {"type": "mrkdwn", "text": numbers}},
        {"type": "context", "elements": [{"type": "mrkdwn", "text": context}]},
    ]
    if anomaly.recent:
        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"Last {len(anomaly.recent)} points: `{sparkline(anomaly.recent)}`",
                },
            }
        )
    blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": recommendation}})

    buttons = []
    if series.console_url:
        buttons.append(_button("Open in console", series.console_url))
    if spec.runbook:
        buttons.append(_button("Runbook", spec.runbook))
    if buttons:
        blocks.append({"type": "actions", "elements": buttons})

    fallback = (
        f"[{severity}] {provider} {spec.name} {series.metric}: "
        f"{fmt(det.observed)} vs baseline {fmt(det.center)}"
    )
    return {
        "text": fallback,
        "attachments": [{"color": COLORS.get(anomaly.severity, COLORS["critical"]), "blocks": blocks}],
    }


def build_overflow_payload(count: int, cap: int) -> dict:
    noun = "anomaly" if count == 1 else "anomalies"
    return {"text": f"{count} more {noun} suppressed (limit of {cap} alerts per run)"}


def build_heartbeat_payload(
    now, *, checked: int, total: int, anomalies: int, failed: list[str]
) -> dict:
    """Routine "still alive" message. Lists failed metrics by name only, never error text."""
    degraded = bool(failed)
    status = "DEGRADED" if degraded else "OK"
    noun = "anomaly" if anomalies == 1 else "anomalies"
    title = f"*Heartbeat: {status}*"
    errors = f"{len(failed)} fetch error{'' if len(failed) == 1 else 's'}"
    summary = (
        f"Checked *{checked}* of *{total}* metrics | *{anomalies}* {noun} right now | *{errors}*"
    )
    blocks = [
        {"type": "section", "text": {"type": "mrkdwn", "text": title}},
        {"type": "section", "text": {"type": "mrkdwn", "text": summary}},
    ]
    if failed:
        shown = failed[:10]
        extra = f" and {len(failed) - len(shown)} more" if len(failed) > len(shown) else ""
        listing = ", ".join(f"`{esc(name)}`" for name in shown) + extra
        blocks.append(
            {"type": "section", "text": {"type": "mrkdwn", "text": f"Could not fetch: {listing}"}}
        )
    blocks.append(
        {"type": "context", "elements": [{"type": "mrkdwn", "text": f"Run at {_stamp(now)} UTC"}]}
    )
    fallback = (
        f"Heartbeat {status}: {checked}/{total} metrics checked, {anomalies} {noun}, {errors}"
    )
    return {
        "text": fallback,
        "attachments": [{"color": COLORS["warning" if degraded else "ok"], "blocks": blocks}],
    }


# Digest rows are routine.DigestRow; only their attributes are used here, so no import.
_DIGEST_ICONS = {
    "critical": ":red_circle:",
    "warning": ":large_orange_circle:",
    "failed": ":warning:",
    "learning": ":hourglass_flowing_sand:",
    "ok": ":large_green_circle:",
}
_DIGEST_COUNT_LABELS = (
    ("critical", "critical"),
    ("warning", "warning"),
    ("failed", "fetch error"),
    ("learning", "learning"),
    ("ok", "ok"),
)
MAX_DIGEST_ROWS = 100
_SECTION_LIMIT = 2900  # Slack rejects section text over 3000 characters


def _digest_line(row) -> str:
    icon = _DIGEST_ICONS[row.status]
    head = f"{icon} *{esc(row.name)}* ({PROVIDER_LABELS.get(row.provider, row.provider)})"
    if row.status == "failed":
        return f"{head}: could not fetch"  # never the error text: it can name ARNs or IDs
    unit = f" {esc(row.unit)}" if row.unit else ""
    latest = "no data" if row.latest is None else f"{fmt(row.latest)}{unit}"
    if row.status == "learning":
        return f"{head}: {latest}, {row.points} of {row.needed} points before a baseline"
    line = f"{head}: {latest} vs {row.center_label} {fmt(row.center)}{unit}"
    if row.recent:
        line += f" `{sparkline(list(row.recent))}`"
    return line


def _chunk(lines: list[str]) -> list[str]:
    chunks, current = [], ""
    for line in lines:
        if current and len(current) + 1 + len(line) > _SECTION_LIMIT:
            chunks.append(current)
            current = line
        else:
            current = f"{current}\n{line}" if current else line
    if current:
        chunks.append(current)
    return chunks


def build_digest_payload(now, rows) -> dict:
    """Routine per-metric health summary, worst first. Rows arrive already sorted."""
    counts = {key: sum(1 for r in rows if r.status == key) for key, _ in _DIGEST_COUNT_LABELS}
    if counts["critical"] or counts["warning"]:
        status, color = "ALERTING", COLORS["critical" if counts["critical"] else "warning"]
    elif counts["failed"]:
        status, color = "DEGRADED", COLORS["warning"]
    else:
        status, color = "OK", COLORS["ok"]

    parts = []
    for key, label in _DIGEST_COUNT_LABELS:
        n = counts[key]
        if n:
            plural = "s" if label == "fetch error" and n != 1 else ""
            parts.append(f"{n} {label}{plural}")
    metric_noun = "metric" if len(rows) == 1 else "metrics"
    summary = f"*{len(rows)}* {metric_noun}" + "".join(f" | {part}" for part in parts)

    shown = rows[:MAX_DIGEST_ROWS]
    lines = [_digest_line(r) for r in shown]
    if len(rows) > len(shown):
        lines.append(f"_and {len(rows) - len(shown)} more_")

    blocks = [
        {"type": "section", "text": {"type": "mrkdwn", "text": f"*Health digest: {status}*"}},
        {"type": "section", "text": {"type": "mrkdwn", "text": summary}},
    ]
    blocks += [{"type": "section", "text": {"type": "mrkdwn", "text": c}} for c in _chunk(lines)]
    blocks.append(
        {"type": "context", "elements": [{"type": "mrkdwn", "text": f"Run at {_stamp(now)} UTC"}]}
    )
    fallback = f"Health digest {status}: {len(rows)} {metric_noun}" + "".join(f", {p}" for p in parts)
    return {"text": fallback, "attachments": [{"color": color, "blocks": blocks}]}


def _button(label: str, url: str) -> dict:
    return {"type": "button", "text": {"type": "plain_text", "text": label}, "url": url}
