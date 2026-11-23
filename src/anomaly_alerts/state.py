"""Dedup and cooldown, kept in a small JSON document keyed by anomaly fingerprint.

The document lives in a local file, in an S3 object when the location is `s3://bucket/key`,
or in an Azure blob when it is `https://<account>.blob.core.windows.net/<container>/<path>`
(for hosts with no mounted disk, such as Lambda and Azure Functions).
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

from . import azureblob
from .models import SEVERITY_RANK

log = logging.getLogger(__name__)

_KEEP = timedelta(days=7)


class _FileBackend:
    def __init__(self, path: Path):
        self.path = Path(path)

    def __str__(self) -> str:
        return str(self.path)

    def read(self) -> str | None:
        try:
            return self.path.read_text()
        except FileNotFoundError:
            return None

    def write(self, text: str) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as fh:
                fh.write(text)
            os.replace(tmp, self.path)
        except BaseException:
            os.unlink(tmp)
            raise

    def modified(self) -> datetime | None:
        try:
            return datetime.fromtimestamp(self.path.stat().st_mtime, UTC)
        except OSError:
            return None


class _S3Backend:
    def __init__(self, uri: str):
        bucket, _, key = uri.removeprefix("s3://").partition("/")
        if not bucket or not key:
            raise ValueError(f"state location must look like s3://bucket/key, got {uri!r}")
        self.uri, self.bucket, self.key = uri, bucket, key
        self._client = None

    def __str__(self) -> str:
        return self.uri

    def _s3(self):
        if self._client is None:
            import boto3  # imported late so the AWS extra stays optional

            self._client = boto3.client("s3")
        return self._client

    def read(self) -> str | None:
        client = self._s3()
        try:
            return client.get_object(Bucket=self.bucket, Key=self.key)["Body"].read().decode()
        except client.exceptions.NoSuchKey:
            return None

    def write(self, text: str) -> None:
        self._s3().put_object(
            Bucket=self.bucket, Key=self.key, Body=text.encode(), ContentType="application/json"
        )

    def modified(self) -> datetime | None:
        client = self._s3()
        try:
            return client.head_object(Bucket=self.bucket, Key=self.key)["LastModified"]
        except client.exceptions.ClientError:
            return None


class _BlobBackend:
    def __init__(self, url: str):
        azureblob.parse(url)  # reject a bad URL up front
        self.url = url
        self._client = None

    def __str__(self) -> str:
        return self.url

    def _blob(self):
        if self._client is None:
            self._client = azureblob.client(self.url)
        return self._client

    def read(self) -> str | None:
        try:
            return self._blob().download_blob().readall().decode()
        except Exception as exc:  # noqa: BLE001
            if azureblob.is_not_found(exc):
                return None
            raise

    def write(self, text: str) -> None:
        self._blob().upload_blob(text.encode(), overwrite=True)

    def modified(self) -> datetime | None:
        try:
            return self._blob().get_blob_properties().last_modified
        except Exception as exc:  # noqa: BLE001
            if azureblob.is_not_found(exc):
                return None
            raise


def _backend(location: str | Path):
    if isinstance(location, str) and location.startswith("s3://"):
        return _S3Backend(location)
    if azureblob.is_blob_url(location):
        return _BlobBackend(location)
    return _FileBackend(Path(location))


class StateStore:
    def __init__(self, location: str | Path, cooldown_seconds: int):
        self._backend = _backend(location)
        self.cooldown = timedelta(seconds=cooldown_seconds)
        self._entries: dict[str, dict] = {}

    def load(self) -> None:
        try:
            text = self._backend.read()
            data = json.loads(text) if text is not None else {}
            self._entries = data if isinstance(data, dict) else {}
        except Exception as exc:  # noqa: BLE001
            # A bad or unreachable state document must not stop alerting; worst case is a repeat alert.
            log.warning("ignoring unreadable state %s: %s", self._backend, exc)
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
        entry = self._entries.setdefault(fingerprint, {})
        entry.update({"at": now.isoformat(), "severity": severity})

    # An alert posted with the bot token is a thread: its message id, the message as posted
    # (to rebuild it as resolved) and when it opened are kept until it resolves.

    def thread(self, fingerprint: str) -> dict | None:
        entry = self._entries.get(fingerprint)
        return entry if entry and entry.get("ts") else None

    def open_thread(self, fingerprint: str, ts: str, payload: dict, now: datetime) -> None:
        entry = self._entries.setdefault(fingerprint, {})
        entry.update({"ts": ts, "payload": payload, "opened": now.isoformat(), "quiet": 0})

    def update_thread(self, fingerprint: str, payload: dict) -> None:
        self._entries[fingerprint]["payload"] = payload
        self._entries[fingerprint]["quiet"] = 0

    def open_threads(self) -> dict[str, dict]:
        return {fp: e for fp, e in self._entries.items() if e.get("ts")}

    def quiet_run(self, fingerprint: str) -> int:
        """Count one more run in which this open alert was not detected, and return the count."""
        entry = self._entries[fingerprint]
        entry["quiet"] = int(entry.get("quiet", 0)) + 1
        return entry["quiet"]

    def still_firing(self, fingerprint: str) -> None:
        if fingerprint in self._entries:
            self._entries[fingerprint]["quiet"] = 0

    def close_thread(self, fingerprint: str) -> None:
        """The alert resolved. The cooldown entry stays, so a quick return does not re-alert at once."""
        entry = self._entries.get(fingerprint, {})
        for key in ("ts", "payload", "opened", "quiet"):
            entry.pop(key, None)

    def last_saved(self) -> datetime | None:
        """When an alert run last saved this file, or None if none has. Every run saves it."""
        try:
            return self._backend.modified()
        except Exception as exc:  # noqa: BLE001
            log.warning("cannot read state time %s: %s", self._backend, exc)
            return None

    def alerted_since(self, since: datetime) -> int:
        """Anomalies alerted at or after `since`. Only the latest alert per anomaly is kept."""
        return sum(1 for e in self._entries.values() if (at := _at(e)) and at >= since)

    def save(self, now: datetime) -> None:
        self._entries = {fp: e for fp, e in self._entries.items() if _recent(e, now)}
        self._backend.write(json.dumps(self._entries, indent=2, sort_keys=True))


def _at(entry: dict) -> datetime | None:
    try:
        return datetime.fromisoformat(entry["at"])
    except (KeyError, TypeError, ValueError):
        return None


def _recent(entry: dict, now: datetime) -> bool:
    at = _at(entry)
    return at is not None and now - at <= _KEEP
