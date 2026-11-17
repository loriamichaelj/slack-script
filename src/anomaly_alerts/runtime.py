"""Start-up steps every host shares: where the config comes from, and where secrets come from.

Both are chosen by the environment, so one image runs unchanged on Cloud Run, Azure Container
Apps and AWS Lambda.

Config (the --config value, or ANOMALY_CONFIG for Lambda):
  a local path          used as it is
  s3://bucket/key       downloaded at start
  https://<account>.blob.core.windows.net/<container>/<blob>   downloaded at start
  inline                the file itself, base64 encoded, in ANOMALY_CONFIG_B64

Secrets:
  <NAME>_SECRET_ID      where the value of the variable <NAME> is kept, for example
                        SLACK_WEBHOOK_URL_SECRET_ID=ssm:/anomaly-alerts/slack-webhook sets
                        SLACK_WEBHOOK_URL. A variable that is already set is left alone.
                          ssm:/path   an AWS Systems Manager SecureString parameter (free)
                          anything else   the id of an AWS Secrets Manager secret
                        Cloud Run and Container Apps inject secrets as variables themselves.

LOG_LEVEL (DEBUG, INFO by default, WARNING or ERROR) sets the level where the host has already
installed its own log handler.
"""

from __future__ import annotations

import base64
import logging
import os

from . import azureblob

_SECRET_SUFFIX = "_SECRET_ID"
_SSM_PREFIX = "ssm:"
_DOWNLOADED_CONFIG = "/tmp/config.yaml"  # the one place every host lets the process write
INLINE = "inline"


def _boto3_client(service: str):
    import boto3  # imported late so the AWS extra stays optional

    return boto3.client(service)


def configure_logging(environ=None) -> None:
    """Lambda installs its own log handler at WARNING before our code runs, which makes the
    CLI's logging.basicConfig do nothing. Set the level here so the run summary shows."""
    environ = os.environ if environ is None else environ
    level = logging.getLevelName(str(environ.get("LOG_LEVEL", "INFO")).upper())
    logging.getLogger().setLevel(level if isinstance(level, int) else logging.INFO)


def load_secrets(environ=None, client_factory=None) -> list[str]:
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
    factory = client_factory or _boto3_client
    clients: dict[str, object] = {}

    def client(service: str):
        if service not in clients:
            try:
                clients[service] = factory(service)
            except Exception as exc:
                raise RuntimeError(f"cannot read secrets: {type(exc).__name__} starting the AWS client") from exc
        return clients[service]

    for name, secret in wanted.items():
        # Only the variable name is logged: never the value, and no error text that could hold it.
        try:
            if secret.startswith(_SSM_PREFIX):
                parameter = client("ssm").get_parameter(Name=secret[len(_SSM_PREFIX):], WithDecryption=True)
                environ[name] = parameter["Parameter"]["Value"]
            else:
                environ[name] = client("secretsmanager").get_secret_value(SecretId=secret)["SecretString"]
        except RuntimeError:
            raise
        except Exception as exc:
            raise RuntimeError(f"could not read the secret for {name}: {type(exc).__name__}") from exc
    return sorted(wanted)


def inline_config(environ=None, destination: str = _DOWNLOADED_CONFIG) -> str:
    """Write the config held in ANOMALY_CONFIG_B64 to a file, and return its path."""
    environ = os.environ if environ is None else environ
    encoded = environ.get("ANOMALY_CONFIG_B64")
    if not encoded:
        raise ValueError("the config is 'inline' but ANOMALY_CONFIG_B64 is not set")
    try:
        data = base64.b64decode(encoded, validate=True)
    except ValueError as exc:
        raise ValueError("ANOMALY_CONFIG_B64 is not valid base64") from exc
    with open(destination, "wb") as fh:
        fh.write(data)
    return destination


def resolve_config(
    path: str,
    client_factory=None,
    destination: str = _DOWNLOADED_CONFIG,
    blob_factory=azureblob.client,
    environ=None,
) -> str:
    """A local path is used as it is. Anything else is fetched, and its local copy returned."""
    if path == INLINE:
        return inline_config(environ, destination)
    if azureblob.is_blob_url(path):
        with open(destination, "wb") as fh:
            fh.write(blob_factory(path).download_blob().readall())
        return destination
    if path.startswith("s3://"):
        bucket, _, key = path.removeprefix("s3://").partition("/")
        if not bucket or not key:
            raise ValueError(f"the config must look like s3://bucket/key, got {path!r}")
        (client_factory or _boto3_client)("s3").download_file(bucket, key, destination)
        return destination
    return path
