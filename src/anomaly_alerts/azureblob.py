"""Azure Blob helpers shared by the cooldown state and the Function's config download.

A blob is named by its URL: https://<account>.blob.core.windows.net/<container>/<path>.
Sign-in is DefaultAzureCredential, which in a Function is its managed identity (set
AZURE_CLIENT_ID to pick a user-assigned one). No storage keys are used or needed.
"""

from __future__ import annotations

from urllib.parse import urlparse

_SUFFIX = ".blob.core.windows.net"


def is_blob_url(value) -> bool:
    if not isinstance(value, str) or not value.startswith("https://"):
        return False
    host = urlparse(value).hostname or ""
    return host.endswith(_SUFFIX)


def parse(url: str) -> tuple[str, str, str]:
    """Returns the account URL, the container and the blob path."""
    parts = urlparse(url)
    container, _, blob = parts.path.lstrip("/").partition("/")
    if not is_blob_url(url) or not container or not blob:
        raise ValueError(f"must look like https://<account>{_SUFFIX}/<container>/<blob>, got {url!r}")
    return f"{parts.scheme}://{parts.netloc}", container, blob


def client(url: str):
    """A BlobClient for the URL, signed in with the managed identity."""
    from azure.identity import DefaultAzureCredential  # imported late so the Azure extra stays optional
    from azure.storage.blob import BlobClient

    account_url, container, blob = parse(url)
    return BlobClient(account_url, container_name=container, blob_name=blob, credential=DefaultAzureCredential())


def is_not_found(exc: Exception) -> bool:
    """True for a missing blob. Checked by status or name so the Azure SDK is not needed to test it."""
    return getattr(exc, "status_code", None) == 404 or type(exc).__name__ == "ResourceNotFoundError"
