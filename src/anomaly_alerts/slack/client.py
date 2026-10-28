"""Post a payload to a Slack incoming webhook. Standard library only.

The webhook URL is a secret: it is never logged or included in an error message.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request

MAX_RETRY_WAIT = 30.0


class SlackError(Exception):
    pass


def post(
    url: str,
    payload: dict,
    *,
    timeout: float = 10.0,
    retries: int = 3,
    opener=urllib.request.urlopen,
    sleep=time.sleep,
) -> None:
    body = json.dumps(payload).encode()
    last = "no attempt made"
    for attempt in range(retries + 1):
        request = urllib.request.Request(
            url, data=body, headers={"Content-Type": "application/json"}, method="POST"
        )
        wait = 2.0**attempt
        try:
            with opener(request, timeout=timeout) as response:
                if response.status == 200:
                    return
                raise SlackError(f"Slack returned HTTP {response.status}")
        except urllib.error.HTTPError as exc:
            last = f"Slack returned HTTP {exc.code}"
            if exc.code != 429 and exc.code < 500:
                raise SlackError(last) from None
            if exc.code == 429:
                try:
                    wait = float(exc.headers.get("Retry-After", wait))
                except (TypeError, ValueError):
                    pass
        except urllib.error.URLError as exc:
            last = f"could not reach Slack: {exc.reason}"
        if attempt < retries:
            sleep(min(wait, MAX_RETRY_WAIT))
    raise SlackError(f"{last} (gave up after {retries + 1} attempts)")
