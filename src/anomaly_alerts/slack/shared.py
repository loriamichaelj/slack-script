"""One Slack message per routine report, shared by every cloud.

Each cloud's job runs on its own, a few minutes apart. Each one finds the message for the
current slot (or posts it, if it is first) and puts its own section in. The sections of the
other clouds are kept as they are, so the message fills in as the jobs report. A cloud that has
not reported yet is listed as waiting, which is also how a job that never ran shows up.

A section's blocks carry the block id `<cloud>:<n>`, so a later job can tell them apart. The
message's metadata names its report and slot, and holds each cloud's level for the overall status.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from .blocks import PROVIDER_LABELS, Report, _stamp
from .bot import EVENT_TYPE, Found, SlackBot
from .client import SlackError

log = logging.getLogger(__name__)

REPORT_NAMES = {"heartbeat": "Heartbeat", "digest": "Health digest", "cost": "Cost report"}
_ICONS = {"ok": ":large_green_circle:", "warning": ":large_orange_circle:", "critical": ":red_circle:"}
_OVERALL = {"ok": "OK", "warning": "WARNING", "critical": "CRITICAL"}
_RANK = {"ok": 0, "warning": 1, "critical": 2}
_MAX_SECTION_BLOCKS = 14  # Slack allows 50 blocks in a message; three clouds, a head and a footer
_LOOK_BACK = timedelta(hours=7)  # longer than the six hour heartbeat slot
ATTEMPTS = 3


def slot_key(kind: str, now: datetime, time_zone: str) -> str:
    """Which message this run belongs to. Heartbeats come every six hours, the others daily,
    in the local time the schedules are written in."""
    local = now.astimezone(ZoneInfo(time_zone))
    if kind == "heartbeat":
        return f"{local:%Y-%m-%d}-{local.hour // 6 * 6:02d}"
    return f"{local:%Y-%m-%d}"


def section_blocks(provider: str, report: Report) -> list[dict]:
    """This cloud's report as blocks: a header line, then the report's own body."""
    detail = f" ({report.detail})" if report.detail else ""
    label = PROVIDER_LABELS.get(provider, provider)
    header = {
        "type": "section",
        "text": {"type": "mrkdwn", "text": f"{_ICONS[report.level]} *{label}*: {report.label}{detail}"},
    }
    body = list(report.body[: _MAX_SECTION_BLOCKS - 1])
    if len(report.body) > len(body):
        body.append(
            {"type": "context", "elements": [{"type": "mrkdwn", "text": "_The rest does not fit in the message._"}]}
        )
    blocks = [header, *body]
    return [{**block, "block_id": f"{provider}:{i}"} for i, block in enumerate(blocks)]


def split_sections(blocks: list[dict]) -> dict[str, list[dict]]:
    """Group a message's blocks by the cloud that wrote them. Head and footer have no cloud."""
    sections: dict[str, list[dict]] = {}
    for block in blocks:
        cloud, sep, _ = str(block.get("block_id", "")).partition(":")
        if sep and cloud in PROVIDER_LABELS:
            sections.setdefault(cloud, []).append(block)
    return sections


def compose(
    kind: str,
    slot: str,
    now: datetime,
    sections: dict[str, list[dict]],
    levels: dict[str, str],
    expected: tuple[str, ...],
) -> tuple[dict, dict]:
    """The message and its metadata, from every cloud's section so far."""
    order = [p for p in expected if p in sections] + sorted(p for p in sections if p not in expected)
    waiting = [p for p in expected if p not in sections]
    overall = max((levels.get(p, "ok") for p in order), key=lambda lv: _RANK.get(lv, 0), default="ok")
    name = REPORT_NAMES[kind]
    head = f"*{name}: {_OVERALL.get(overall, 'OK')}*"
    foot = f"Updated {_stamp(now)} UTC"
    if waiting:
        foot = f":hourglass_flowing_sand: Waiting for {', '.join(PROVIDER_LABELS.get(p, p) for p in waiting)} | {foot}"
    blocks = [{"type": "section", "block_id": "head", "text": {"type": "mrkdwn", "text": head}}]
    for provider in order:
        blocks += sections[provider]
    blocks.append({"type": "context", "block_id": "foot", "elements": [{"type": "mrkdwn", "text": foot}]})
    text = f"{name} {_OVERALL.get(overall, 'OK')}: " + ", ".join(PROVIDER_LABELS.get(p, p) for p in order)
    metadata = {
        "event_type": EVENT_TYPE,
        "event_payload": {"kind": kind, "slot": slot, "levels": {p: levels.get(p, "ok") for p in order}},
    }
    return {"text": text, "blocks": blocks}, metadata


def preview(report: Report, *, kind: str, provider: str, now: datetime, expected: tuple[str, ...], time_zone: str) -> dict:
    """The message as it would look with only this cloud's section, for a dry run."""
    message, _ = compose(
        kind,
        slot_key(kind, now, time_zone),
        now,
        {provider: section_blocks(provider, report)},
        {provider: report.level},
        expected,
    )
    return message


def publish(
    bot: SlackBot,
    report: Report,
    *,
    kind: str,
    provider: str,
    now: datetime,
    expected: tuple[str, ...],
    time_zone: str,
    sleep=time.sleep,
) -> None:
    """Put this cloud's section in the slot's message. Two jobs can write at the same moment, so
    after each write the message is read again, and the write is repeated if this section is gone."""
    slot = slot_key(kind, now, time_zone)
    mine = section_blocks(provider, report)
    since = (now - _LOOK_BACK).timestamp()
    for attempt in range(ATTEMPTS):
        found = bot.find(kind, slot, since)
        sections: dict[str, list[dict]] = {}
        levels: dict[str, str] = {}
        for message in found:  # oldest first, so a newer copy of a cloud's section wins
            sections.update(split_sections(message.blocks))
            levels.update(message.levels)
        sections[provider] = mine
        levels[provider] = report.level
        message, metadata = compose(kind, slot, now, sections, levels, expected)
        if found:
            bot.update(found[0].ts, message, metadata)
        else:
            bot.post(message, metadata)
        for extra in found[1:]:  # two clouds posted at once: the older message is the one kept
            bot.delete(extra.ts)

        checked = bot.find(kind, slot, since)
        if len(checked) == 1 and provider in split_sections(checked[0].blocks):
            return
        log.warning("%s section is not in the shared %s message yet (attempt %d)", provider, kind, attempt + 1)
        sleep(1.0 + attempt)
    raise SlackError(f"could not keep the {provider} section in the shared {kind} message")


__all__ = ["publish", "preview", "compose", "slot_key", "section_blocks", "split_sections", "Found"]
