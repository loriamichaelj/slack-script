"""AWS Lambda entry point. The event picks the job; the environment says where things are.

Event: {"command": "run"|"routine", "kind": "heartbeat"|"digest"|"cost", "dry_run": false}

The start-up steps are in runtime.py, shared with the CLI: ANOMALY_CONFIG names the config
(a path, s3://bucket/key or an Azure blob URL), and <NAME>_SECRET_ID variables name secrets.
"""

from __future__ import annotations

import os

from . import cli
from .runtime import configure_logging, inline_config, load_secrets, resolve_config

__all__ = ["lambda_handler", "run_event", "configure_logging", "inline_config", "load_secrets", "resolve_config"]


def lambda_handler(event, context):
    return run_event(event)


def run_event(event) -> dict:
    """Run the job the event names. A failure raises, so the host records it."""
    event = event or {}
    configure_logging()
    load_secrets()
    config = resolve_config(os.environ.get("ANOMALY_CONFIG", "config/config.yaml"))
    argv = [event.get("command", "run"), "--config", config]
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
