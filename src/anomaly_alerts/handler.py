"""AWS Lambda entry point. The event picks the job; the config path comes from the environment.

Event: {"command": "run"|"routine", "kind": "heartbeat"|"digest"|"cost", "dry_run": false}
Environment: ANOMALY_CONFIG (path to the config file in the package or a mounted layer).
"""

from __future__ import annotations

import os

from . import cli


def lambda_handler(event, context):
    event = event or {}
    argv = [event.get("command", "run"), "--config", os.environ.get("ANOMALY_CONFIG", "config/config.yaml")]
    if argv[0] == "routine":
        argv += ["--kind", event.get("kind", "heartbeat")]
    if event.get("dry_run"):
        argv.append("--dry-run")
    if event.get("only"):
        argv += ["--only", event["only"]]
    code = cli.main(argv)
    if code != 0:
        # Surface failures to Lambda so retries, alarms and metrics see them.
        raise RuntimeError(f"anomaly-alerts exited with code {code}")
    return {"exit_code": code}
