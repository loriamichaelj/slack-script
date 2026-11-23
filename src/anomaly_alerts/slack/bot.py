"""The few Slack Web API calls the shared routine message needs. Standard library only.

An incoming webhook can only post new messages. To keep one message for all the clouds, each
cloud's job finds it, edits it, or posts it if it is the first, which takes a bot token with the
`chat:write` scope and `channels:history` (`groups:history` for a private channel). The token is
a secret: it is never logged or put in an error message, and an error names only Slack's own
error code, such as `channel_not_found`.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

from .client import MAX_RETRY_WAIT, SlackError

API = "https://slack.com/api/"
EVENT_TYPE = "anomaly_alerts_routine"  # marks the messages this app keeps, in their metadata


@dataclass(frozen=True)
class Found:
    """A shared message already in the channel."""

    ts: str
    blocks: list[dict]
    levels: dict[str, str] = field(default_factory=dict)  # each cloud's level, from the metadata


class SlackBot:
    def __init__(
        self,
        token: str,
        channel: str,
        *,
        timeout: float = 10.0,
        retries: int = 2,
        opener=urllib.request.urlopen,
        sleep=time.sleep,
    ):
        self._token = token
        self.channel = channel
        self._timeout = timeout
        self._retries = retries
        self._opener = opener
        self._sleep = sleep

    def _call(self, method: str, fields: dict, *, form: bool = False) -> dict:
        if form:
            body = urllib.parse.urlencode(fields).encode()
            content_type = "application/x-www-form-urlencoded"
        else:
            body = json.dumps(fields).encode()
            content_type = "application/json; charset=utf-8"
        last = "no attempt made"
        for attempt in range(self._retries + 1):
            request = urllib.request.Request(
                API + method,
                data=body,
                headers={"Content-Type": content_type, "Authorization": f"Bearer {self._token}"},
                method="POST",
            )
            wait = 2.0**attempt
            try:
                with self._opener(request, timeout=self._timeout) as response:
                    reply = json.loads(response.read().decode() or "{}")
            except urllib.error.HTTPError as exc:
                last = f"Slack {method} returned HTTP {exc.code}"
                if exc.code != 429 and exc.code < 500:
                    raise SlackError(last) from None
                if exc.code == 429:
                    try:
                        wait = float(exc.headers.get("Retry-After", wait))
                    except (TypeError, ValueError):
                        pass
            except urllib.error.URLError as exc:
                last = f"could not reach Slack: {exc.reason}"
            except ValueError:
                raise SlackError(f"Slack {method} sent a reply that is not JSON") from None
            else:
                if reply.get("ok"):
                    return reply
                error = str(reply.get("error", "unknown_error"))
                if error != "ratelimited":
                    raise SlackError(f"Slack {method} failed: {error}")
                last = f"Slack {method} was rate limited"
            if attempt < self._retries:
                self._sleep(min(wait, MAX_RETRY_WAIT))
        raise SlackError(f"{last} (gave up after {self._retries + 1} attempts)")

    def find(self, kind: str, slot: str, since: float) -> list[Found]:
        """The shared messages for this report and slot posted since `since` (epoch seconds),
        oldest first. More than one means two clouds posted at the same moment."""
        reply = self._call(
            "conversations.history",
            {
                "channel": self.channel,
                "oldest": f"{since:.6f}",
                "limit": 200,
                "include_all_metadata": "true",
            },
            form=True,
        )
        found = []
        for message in reply.get("messages", []):
            metadata = message.get("metadata") or {}
            payload = metadata.get("event_payload") or {}
            if (
                metadata.get("event_type") == EVENT_TYPE
                and payload.get("kind") == kind
                and payload.get("slot") == slot
            ):
                levels = payload.get("levels")
                found.append(
                    Found(message["ts"], message.get("blocks") or [], levels if isinstance(levels, dict) else {})
                )
        return sorted(found, key=lambda f: float(f.ts))

    def post(self, message: dict, metadata: dict) -> str:
        reply = self._call(
            "chat.postMessage",
            {"channel": self.channel, **message, "metadata": metadata, "unfurl_links": False},
        )
        return reply["ts"]

    def reply(self, thread_ts: str, message: dict, *, broadcast: bool = False) -> str:
        """Post in a message's thread; broadcast also shows the reply in the channel."""
        reply = self._call(
            "chat.postMessage",
            {"channel": self.channel, "thread_ts": thread_ts, "reply_broadcast": broadcast,
             **message, "unfurl_links": False},
        )
        return reply["ts"]

    def update(self, ts: str, message: dict, metadata: dict) -> None:
        self._call("chat.update", {"channel": self.channel, "ts": ts, **message, "metadata": metadata})

    def delete(self, ts: str) -> None:
        self._call("chat.delete", {"channel": self.channel, "ts": ts})
