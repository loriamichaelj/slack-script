"""Tell an external dead-man's-switch service that an alert run finished.

The service (healthchecks.io has a free tier) expects a ping every few minutes and messages Slack
when they stop. It is the one check that still works when a whole cloud is down, because it does
not run inside any of them.

Set HEALTHCHECK_URL to the check's ping URL, or HEALTHCHECK_URL_SECRET_ID to where it is kept
(see runtime.py). With neither set this does nothing. A ping never fails a run, and the URL is
never logged, because anyone who has it can ping the check.
"""

from __future__ import annotations

import logging
import os
import urllib.request

log = logging.getLogger(__name__)

ENV = "HEALTHCHECK_URL"
_TIMEOUT_SECONDS = 5


def _open(request, timeout):
    return urllib.request.urlopen(request, timeout=timeout)  # noqa: S310 (https only, checked below)


def ping(ok: bool, environ=None, opener=_open) -> bool:
    """Ping the configured check. A failed run is reported at <url>/fail, so the service can say
    the job ran and failed, not only that it went quiet. Returns True if a ping was sent."""
    environ = os.environ if environ is None else environ
    url = (environ.get(ENV) or "").strip()
    if not url:
        return False
    if not url.startswith("https://"):
        log.warning("not pinging: %s must be an https URL", ENV)
        return False
    target = url.rstrip("/") + ("" if ok else "/fail")
    try:
        opener(urllib.request.Request(target, method="GET"), _TIMEOUT_SECONDS).close()
    except Exception as exc:  # noqa: BLE001
        # Only the error type is logged: the message can carry the URL.
        log.warning("watchdog ping failed: %s", type(exc).__name__)
        return False
    return True
