"""Provider registry. Cloud SDKs are imported lazily, so a missing SDK only matters if used."""

from __future__ import annotations

import importlib

from .base import Provider

_PROVIDERS = {
    "aws": ("anomaly_alerts.providers.aws", "AwsProvider"),
    "azure": ("anomaly_alerts.providers.azure", "AzureProvider"),
    "gcp": ("anomaly_alerts.providers.gcp", "GcpProvider"),
}


class ProviderPool:
    """Creates each provider once per run, so SDK clients are reused across metrics."""

    def __init__(self, overrides: dict[str, Provider] | None = None):
        self._instances: dict[str, Provider] = dict(overrides or {})

    def get(self, name: str) -> Provider:
        if name not in self._instances:
            module_name, class_name = _PROVIDERS[name]
            module = importlib.import_module(module_name)
            self._instances[name] = getattr(module, class_name)()
        return self._instances[name]
