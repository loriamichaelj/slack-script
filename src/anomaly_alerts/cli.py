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
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from . import actions, config, pipeline, routine, runtime, watchdog
from .cost import CostProviderPool
from .providers import ProviderPool
from .slack import bot, client, shared
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


def _hours(value: str) -> frozenset[int]:
    try:
        hours = frozenset(int(part) for part in value.split(","))
    except ValueError:
        raise argparse.ArgumentTypeError(f"expected hours like 0,6,12,18, got {value!r}") from None
    if not hours or any(h < 0 or h > 23 for h in hours):
        raise argparse.ArgumentTypeError(f"hours must be between 0 and 23, got {value!r}")
    return hours


def _now() -> datetime:
    return datetime.now(UTC)


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
        help="routine report to post: heartbeat (default), digest or cost (routine command only)",
    )
    parser.add_argument(
        "--local-hours",
        type=_hours,
        help="run only when the hour in the slack.shared_message time zone is one of these, such "
        "as 0,6,12,18, and otherwise exit quietly. For a host whose cron is in UTC only: schedule "
        "it at every UTC hour that can be one of these, and daylight saving takes care of itself",
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


def _shared_publisher(cfg: config.Config, kind: str, dry_run: bool):
    """How this job puts its routine report into the message the clouds share, or None to post
    it as its own message. Without the bot token it posts on its own, so a missing secret
    delays the merging but never the report."""
    settings = cfg.slack.shared_message
    if settings is None:
        return None
    if dry_run:
        def preview(report, now):
            message = shared.preview(
                report, kind=kind, provider=settings.cloud, now=now,
                expected=settings.clouds, time_zone=settings.time_zone,
            )
            print(json.dumps(message, indent=2, ensure_ascii=False))
        return preview
    token = os.environ.get(settings.bot_token_env, "")
    if not token:
        log.warning("%s is not set; posting the routine report as its own message", settings.bot_token_env)
        return None
    slack_bot = bot.SlackBot(token, settings.channel)

    def publish(report, now):
        shared.publish(
            slack_bot, report, kind=kind, provider=settings.cloud, now=now,
            expected=settings.clouds, time_zone=settings.time_zone,
        )
    return publish


def main(argv=None) -> int:
    args = _parse(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        stream=sys.stderr,
    )

    try:
        _load_dotenv(Path(".env"))
        # A container host can name the config by URL or inline, and secrets by id, so one
        # image runs the same way everywhere (see runtime.py). A plain path is used as it is.
        runtime.load_secrets()
        cfg = config.load(runtime.resolve_config(args.config))
        rules = actions.load_rules(cfg.actions_path)
        if args.local_hours is not None:
            settings = cfg.slack.shared_message
            if settings is None:
                raise config.ConfigError("--local-hours needs slack.shared_message, for its time zone")
            hour = _now().astimezone(ZoneInfo(settings.time_zone)).hour
            if hour not in args.local_hours:
                log.info(
                    "it is hour %d in %s, not one of %s: nothing to do",
                    hour, settings.time_zone, sorted(args.local_hours),
                )
                return 0
        is_routine = args.command == "routine"
        if is_routine and args.kind == "cost" and cfg.cost is None:
            raise config.ConfigError("the cost report needs a cost section in the config")
        env_name = _webhook_env(cfg, is_routine)
        webhook = os.environ.get(env_name, "")
        if not webhook and not args.dry_run:
            raise config.ConfigError(
                f"environment variable {env_name} is not set (use --dry-run to skip Slack)"
            )
    except (config.ConfigError, ValueError, RuntimeError) as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return 2

    if args.dry_run:
        def post(payload: dict) -> None:
            print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        def post(payload: dict) -> None:
            client.post(webhook, payload)

    if is_routine:
        pool = CostProviderPool() if args.kind == "cost" else ProviderPool()
        publish = _shared_publisher(cfg, args.kind, args.dry_run)
        result = routine.run(args.kind, cfg, pool, post, only=args.only, publish=publish)
        log.info(
            "routine %s complete: %d of %d fetched, %d flagged, %d fetch errors, %d post errors",
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
    if not args.dry_run:
        watchdog.ping(result.ok)
    return 0 if result.ok else 1
