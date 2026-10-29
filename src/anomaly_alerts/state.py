"""Dedup and cooldown, kept in a small JSON file keyed by anomaly fingerprint."""

from __future__ import annotations

import json
import logging
import os
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .models import SEVERITY_RANK

log = logging.getLogger(__name__)

_KEEP = timedelta(days=7)


class StateStore:
    def __init__(self, path: Path, cooldown_seconds: int):
        self.path = Path(path)
        self.cooldown = timedelta(seconds=cooldown_seconds)
        self._entries: dict[str, dict] = {}

    def load(self) -> None:
        try:
            data = json.loads(self.path.read_text())
            self._entries = data if isinstance(data, dict) else {}
        except FileNotFoundError:
            self._entries = {}
        except (OSError, ValueError) as exc:
            # A bad state file must not stop alerting; worst case is a repeat alert.
            log.warning("ignoring unreadable state file %s: %s", self.path, exc)
            self._entries = {}

    def allow(self, fingerprint: str, severity: str, now: datetime) -> bool:
        """True if this anomaly should alert: no recent alert, cooldown over, or it escalated."""
        entry = self._entries.get(fingerprint)
        if entry is None:
            return True
        try:
            last = datetime.fromisoformat(entry["at"])
        except (KeyError, ValueError):
            return True
        if now - last >= self.cooldown:
            return True
        return SEVERITY_RANK[severity] > SEVERITY_RANK.get(entry.get("severity"), 0)

    def record(self, fingerprint: str, severity: str, now: datetime) -> None:
        self._entries[fingerprint] = {"at": now.isoformat(), "severity": severity}

    def last_saved(self) -> datetime | None:
        """When an alert run last saved this file, or None if none has. Every run saves it."""
        try:
            return datetime.fromtimestamp(self.path.stat().st_mtime, UTC)
        except OSError:
            return None

    def alerted_since(self, since: datetime) -> int:
        """Anomalies alerted at or after `since`. Only the latest alert per anomaly is kept."""
        return sum(1 for e in self._entries.values() if (at := _at(e)) and at >= since)

    def save(self, now: datetime) -> None:
        self._entries = {fp: e for fp, e in self._entries.items() if _recent(e, now)}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as fh:
                json.dump(self._entries, fh, indent=2, sort_keys=True)
            os.replace(tmp, self.path)
        except BaseException:
            os.unlink(tmp)
            raise


def _at(entry: dict) -> datetime | None:
    try:
        return datetime.fromisoformat(entry["at"])
    except (KeyError, TypeError, ValueError):
        return None


def _recent(entry: dict, now: datetime) -> bool:
    at = _at(entry)
    return at is not None and now - at <= _KEEP
