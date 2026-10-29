"""Cost adapter registry. Like the metric providers, SDKs are imported lazily."""

from __future__ import annotations

import importlib

from .base import CostProvider

# Filled in as each cloud's adapter lands.
_PROVIDERS: dict[str, tuple[str, str]] = {
    "aws": ("anomaly_alerts.cost.aws", "AwsCostProvider"),
    "azure": ("anomaly_alerts.cost.azure", "AzureCostProvider"),
}


class CostProviderPool:
    """Creates each cost adapter once per run."""

    def __init__(self, overrides: dict[str, CostProvider] | None = None):
        self._instances: dict[str, CostProvider] = dict(overrides or {})

    def get(self, name: str) -> CostProvider:
        if name not in self._instances:
            if name not in _PROVIDERS:
                raise RuntimeError(f"cost reports for {name} are not supported yet")
            module_name, class_name = _PROVIDERS[name]
            module = importlib.import_module(module_name)
            self._instances[name] = getattr(module, class_name)()
        return self._instances[name]
