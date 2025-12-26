from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from bv.orchestrator.client import OrchestratorClient


@dataclass(frozen=True)
class Asset:
    name: str
    type: str | None
    value: Any

    def public_value(self) -> Any:
        t = (self.type or "").lower()
        if "secret" in t or "credential" in t:
            return "***"
        return self.value

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "type": self.type,
            "value": self.public_value(),
        }


def list_assets(search: str | None = None) -> list[Asset]:
    client = OrchestratorClient()
    params = {"search": search} if search else None
    resp = client.request("GET", "/api/assets", params=params)

    data = resp.data
    if isinstance(data, dict) and isinstance(data.get("items"), list):
        items = data.get("items")
    elif isinstance(data, list):
        items = data
    else:
        items = []

    assets: list[Asset] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or item.get("key") or "")
        if not name:
            continue
        assets.append(
            Asset(
                name=name,
                type=(str(item.get("type")) if item.get("type") is not None else None),
                value=item.get("value"),
            )
        )

    return assets


def get_asset(name: str) -> Asset:
    if not name:
        raise ValueError("Asset name is required")

    client = OrchestratorClient()

    # Prefer a direct lookup, then fall back to list + exact match.
    try:
        resp = client.request("GET", f"/api/assets/{name}")
        data = resp.data
        if isinstance(data, dict):
            return Asset(
                name=str(data.get("name") or name),
                type=(str(data.get("type")) if data.get("type") is not None else None),
                value=data.get("value"),
            )
    except Exception:
        pass

    for asset in list_assets(search=name):
        if asset.name == name:
            return asset

    raise FileNotFoundError(f"Asset not found: {name}")
