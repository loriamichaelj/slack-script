"""Command line entry point.

Exit codes: 0 ok, 1 a fetch or Slack post failed, 2 bad config or setup.
A routine report exits 1 only if its Slack post failed: fetch errors are shown in the report.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

from . import actions, config, pipeline, routine
from .providers import ProviderPool
from .slack import client
from .state import StateStore

log = logging.getLogger("anomaly_alerts")


def _load_dotenv(path: Path) -> None:
    """Read KEY=VALUE lines into the environment without overriding values already set."""
    if not path.is_file():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip("'\""))


def _parse(argv) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="anomaly-alerts",
        description="Detect metric anomalies on AWS, Azure and GCP and alert Slack.",
    )
    parser.add_argument(
        "command",
        nargs="?",
        choices=["run", "routine"],
        default="run",
        help="run (default) alerts on anomalies; routine posts a scheduled report",
    )
    parser.add_argument("--config", required=True, help="path to the YAML config")
    parser.add_argument(
        "--kind",
        choices=routine.KINDS,
        default="heartbeat",
        help="which routine report to post (routine command only)",
    )
    parser.add_argument("--dry-run", action="store_true", help="print payloads, do not post or save state")
    parser.add_argument("--only", choices=["aws", "azure", "gcp"], help="run one cloud only")
    parser.add_argument("--verbose", action="store_true", help="debug logging")
    return parser.parse_args(argv)


def _webhook_env(cfg: config.Config, is_routine: bool) -> str:
    """Name of the environment variable to post to. Routine reports prefer their own webhook."""
    own = cfg.slack.routine_webhook_env
    if is_routine and own:
        if os.environ.get(own):
            return own
        log.warning("%s is not set; posting the routine report to %s", own, cfg.slack.webhook_env)
    return cfg.slack.webhook_env


def main(argv=None) -> int:
    args = _parse(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        stream=sys.stderr,
    )

    try:
        _load_dotenv(Path(".env"))
        cfg = config.load(args.config)
        rules = actions.load_rules(cfg.actions_path)
        is_routine = args.command == "routine"
        env_name = _webhook_env(cfg, is_routine)
        webhook = os.environ.get(env_name, "")
        if not webhook and not args.dry_run:
            raise config.ConfigError(
                f"environment variable {env_name} is not set (use --dry-run to skip Slack)"
            )
    except config.ConfigError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return 2

    if args.dry_run:
        def post(payload: dict) -> None:
            print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        def post(payload: dict) -> None:
            client.post(webhook, payload)

    if is_routine:
        result = routine.run(args.kind, cfg, ProviderPool(), post, only=args.only)
        log.info(
            "routine %s complete: %d of %d metrics fetched, %d anomalies, %d fetch errors, %d post errors",
            args.kind, result.checked, result.total, result.anomalies,
            result.fetch_errors, result.post_errors,
        )
        return 0 if result.ok else 1

    state = StateStore(cfg.state_path, cfg.slack.cooldown_seconds)
    state.load()
    result = pipeline.run(
        cfg, ProviderPool(), rules, state, post, dry_run=args.dry_run, only=args.only
    )
    log.info(
        "run complete: %d metrics fetched, %d anomalies, %d posted, %d in cooldown, %d over limit, "
        "%d fetch errors, %d post errors",
        result.fetched, result.anomalies, result.posted, result.in_cooldown,
        result.over_limit, result.fetch_errors, result.post_errors,
    )
    return 0 if result.ok else 1
