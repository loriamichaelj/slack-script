"""One Slack thread per alert, from first post to resolved. Needs the bot token.

With only a webhook, every alert is a new message and nothing says when it is over. With the
bot token, the first alert is the top of a thread. While it keeps firing, each reminder after the
cooldown goes in the thread, and the top message is updated to the latest numbers. An
escalation to critical also shows in the channel. When the metric has been quiet for a couple
of runs, the top message turns green and says how long it lasted.

When several new alerts fire in the same run, often from one cause, they arrive as one group: a
summary in the channel with a line per alert, and each alert's details in its thread. The
summary is rebuilt as they change and resolve.
"""

from __future__ import annotations

import copy
from datetime import datetime

from ..detectors import needs_baseline
from ..models import CRITICAL, SPIKE, Anomaly, series_name
from . import blocks
from .bot import SlackBot

EVENT_TYPE = "anomaly_alerts_alert"
RESOLVE_AFTER = 2  # quiet runs in a row before an alert counts as resolved


def _metadata(fingerprint: str) -> dict:
    return {"event_type": EVENT_TYPE, "event_payload": {"fingerprint": fingerprint}}


def follow_up_text(anomaly: Anomaly, opened: datetime, now: datetime, escalated: bool) -> dict:
    det, spec, series = anomaly.detection, anomaly.spec, anomaly.series
    unit = f" {blocks.esc(series.unit)}" if series.unit else ""
    change = blocks.change_text(det.observed, det.center, det.direction, not needs_baseline(spec.detector), unit)
    arrow = "↑" if det.direction == SPIKE else "↓"
    lasted = blocks.duration((now - opened).total_seconds())
    if escalated:
        head = f":red_circle: *Now {det.severity.upper()}* after {lasted}"
    else:
        head = f":repeat: *Still firing* after {lasted}"
    text = f"{head}: {arrow} {blocks.fmt(det.observed)}{unit} ({change})"
    return {"text": text, "blocks": [{"type": "section", "text": {"type": "mrkdwn", "text": text}}]}


def resolved_payload(posted: dict, opened: datetime, now: datetime) -> dict:
    """The alert as posted, turned green, with when it resolved and how long it lasted."""
    payload = copy.deepcopy(posted)
    lasted = blocks.duration((now - opened).total_seconds())
    header = payload.get("blocks", [{}])[0]
    if header.get("type") == "header":
        name = header["text"]["text"].split(" · ", 1)[-1]
        header["text"]["text"] = f":white_check_mark: RESOLVED · {name}"[:150]
    for attachment in payload.get("attachments", []):
        attachment["color"] = blocks.COLORS["ok"]
        attachment.setdefault("blocks", []).insert(
            0,
            {
                "type": "context",
                "elements": [
                    {"type": "mrkdwn", "text": f":white_check_mark: Resolved {blocks.when(now)}, after {lasted}"}
                ],
            },
        )
    payload["text"] = "[RESOLVED] " + str(payload.get("text", "")).split("] ", 1)[-1]
    return payload


_ICONS = {"critical": ":red_circle:", "warning": ":large_orange_circle:"}
GROUP_EVENT_TYPE = "anomaly_alerts_group"


def summary_line(anomaly: Anomaly) -> str:
    """One alert's line in a group: how bad, which metric, and how far it moved."""
    det, spec, series = anomaly.detection, anomaly.spec, anomaly.series
    unit = f" {blocks.esc(series.unit)}" if series.unit else ""
    change = blocks.change_text(det.observed, det.center, det.direction, not needs_baseline(spec.detector), unit)
    provider = blocks.PROVIDER_LABELS.get(series.provider, series.provider)
    return f"{_ICONS.get(det.severity, ':red_circle:')} *{blocks.esc(series_name(spec, series))}* ({provider}) · {change}"


def resolved_line(line: str, opened: datetime, now: datetime) -> str:
    """A group line once its alert resolved: the name kept, the numbers replaced."""
    name = line.split(" ", 1)[-1].split(" · ", 1)[0]
    return f":white_check_mark: {name} · resolved after {blocks.duration((now - opened).total_seconds())}"


def group_payload(members: list[dict]) -> dict:
    """The summary message of a group, from its members' state entries."""
    lines, open_count, worst = [], 0, "warning"
    for member in members:
        if member.get("ts"):
            open_count += 1
            lines.append(member.get("line", ""))
            if member.get("severity") == CRITICAL:
                worst = CRITICAL
        else:
            lines.append(member.get("resolved_line") or member.get("line", ""))
    n = len(members)
    if open_count:
        title = f"{_ICONS[worst]} {n} alerts at once" + (f" · {n - open_count} resolved" if open_count < n else "")
        color = blocks.COLORS[worst]
    else:
        title = f":white_check_mark: RESOLVED · {n} alerts"
        color = blocks.COLORS["ok"]
    body = [
        {"type": "section", "text": {"type": "mrkdwn", "text": "\n".join(lines)[:2900]}},
        {"type": "context", "elements": [{"type": "mrkdwn", "text": "Each alert's details and updates are in the thread."}]},
    ]
    text = f"{n} alerts at once" if open_count else f"Resolved: {n} alerts"
    return {
        "text": text,
        "blocks": [{"type": "header", "text": {"type": "plain_text", "text": title[:150], "emoji": True}}],
        "attachments": [{"color": color, "blocks": body}],
    }


def _group_metadata() -> dict:
    return {"event_type": GROUP_EVENT_TYPE, "event_payload": {}}


class AlertThreads:
    """The Slack calls an alert's thread needs. Every method raises SlackError on failure."""

    def __init__(self, bot: SlackBot):
        self.bot = bot

    def open(self, fingerprint: str, payload: dict) -> str:
        return self.bot.post(payload, _metadata(fingerprint))

    def open_group(self, payload: dict) -> str:
        return self.bot.post(payload, _group_metadata())

    def add_to_group(self, group: str, payload: dict) -> str:
        """Post one alert's details in the group's thread; its id is what later updates edit."""
        return self.bot.reply(group, payload)

    def update_group(self, group: str, payload: dict) -> None:
        self.bot.update(group, payload, _group_metadata())

    def follow_up(
        self, fingerprint: str, ts: str, anomaly: Anomaly, payload: dict, opened: datetime, now: datetime,
        escalated: bool, group: str | None = None,
    ) -> None:
        self.bot.update(ts, payload, _metadata(fingerprint))
        self.bot.reply(group or ts, follow_up_text(anomaly, opened, now, escalated), broadcast=escalated)

    def resolve(
        self, fingerprint: str, ts: str, posted: dict, opened: datetime, now: datetime, group: str | None = None,
    ) -> None:
        self.bot.update(ts, resolved_payload(posted, opened, now), _metadata(fingerprint))
        lasted = blocks.duration((now - opened).total_seconds())
        name = str(posted.get("blocks", [{}])[0].get("text", {}).get("text", "")).split(" · ", 1)[-1]
        what = f"*{blocks.esc(name)}* resolved" if group else "*Resolved*"
        text = f":white_check_mark: {what} after {lasted}: back within its normal range."
        self.bot.reply(group or ts, {"text": text, "blocks": [{"type": "section", "text": {"type": "mrkdwn", "text": text}}]})


def escalated(previous: str | None, current: str) -> bool:
    return current == CRITICAL and previous != CRITICAL
