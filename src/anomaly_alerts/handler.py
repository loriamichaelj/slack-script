"""AWS Lambda entry point. The event picks the job; the environment says where things are.

Event: {"command": "run"|"routine", "kind": "heartbeat"|"digest"|"cost", "dry_run": false}

Environment:
  ANOMALY_CONFIG     path to the config file, or s3://bucket/key to download it at start
  LOG_LEVEL          DEBUG, INFO (default), WARNING or ERROR
  <NAME>_SECRET_ID   id of a Secrets Manager secret whose value becomes the variable <NAME>,
                     for example SLACK_WEBHOOK_URL_SECRET_ID=slack-webhook sets SLACK_WEBHOOK_URL.
                     A variable that is already set is left alone.
"""

from __future__ import annotations

import logging
import os

from . import cli

log = logging.getLogger(__name__)

_SECRET_SUFFIX = "_SECRET_ID"
_DOWNLOADED_CONFIG = "/tmp/config.yaml"  # Lambda's only writable path


def _boto3_client(service: str):
    import boto3  # imported late so the AWS extra stays optional

    return boto3.client(service)


def load_secrets(environ=None, client_factory=_boto3_client) -> list[str]:
    """Set each <NAME> from the secret named by <NAME>_SECRET_ID. Returns the names set."""
    environ = os.environ if environ is None else environ
    wanted = {
        key[: -len(_SECRET_SUFFIX)]: value
        for key, value in environ.items()
        if key.endswith(_SECRET_SUFFIX) and len(key) > len(_SECRET_SUFFIX) and value
    }
    wanted = {name: secret for name, secret in wanted.items() if not environ.get(name)}
    if not wanted:
        return []
    client = client_factory("secretsmanager")
    for name, secret in wanted.items():
        # Only the variable name is logged: never the value, and no error text that could hold it.
        try:
            environ[name] = client.get_secret_value(SecretId=secret)["SecretString"]
        except Exception as exc:
            raise RuntimeError(f"could not read the secret for {name}: {type(exc).__name__}") from exc
    return sorted(wanted)


def resolve_config(path: str, client_factory=_boto3_client, destination: str = _DOWNLOADED_CONFIG) -> str:
    """A local path is used as it is. An s3:// URI is downloaded and its local copy returned."""
    if not path.startswith("s3://"):
        return path
    bucket, _, key = path.removeprefix("s3://").partition("/")
    if not bucket or not key:
        raise ValueError(f"ANOMALY_CONFIG must look like s3://bucket/key, got {path!r}")
    client_factory("s3").download_file(bucket, key, destination)
    return destination


def configure_logging(environ=None) -> None:
    """Lambda installs its own log handler at WARNING before this code runs, which makes
    the CLI's logging.basicConfig do nothing. Set the level here so the run summary shows."""
    environ = os.environ if environ is None else environ
    level = logging.getLevelName(str(environ.get("LOG_LEVEL", "INFO")).upper())
    logging.getLogger().setLevel(level if isinstance(level, int) else logging.INFO)


def lambda_handler(event, context):
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
