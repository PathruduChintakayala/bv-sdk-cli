from __future__ import annotations

from bv.runtime._guard import require_bv_run
from bv.orchestrator import assets as _assets


def get(name: str):
    """Return an asset value by name (generic/legacy).
    
    Fails fast if not authenticated or not running via `bv run`.
    """
    require_bv_run()
    return get_asset(name)


def get_asset(name: str) -> str | int | bool:
    """Fetch a basic asset (text, int, bool) by name with type conversion."""
    require_bv_run()
    from bv.orchestrator.client import OrchestratorClient
    client = OrchestratorClient()
    resp = client.request("GET", f"/api/assets/name/{name}")
    data = resp.data
    val = data.get("value")
    typ = str(data.get("type") or "text").lower()
    
    if typ == "int":
        try:
            return int(val)
        except (ValueError, TypeError):
            return 0
    if typ == "bool":
        if isinstance(val, bool):
            return val
        return str(val).lower() in ("true", "1", "yes")
    return str(val or "")


def get_secret(name: str) -> str:
    """Fetch a secret asset and return its raw encrypted value."""
    require_bv_run()
    from bv.orchestrator.client import OrchestratorClient
    client = OrchestratorClient()
    resp = client.request("GET", f"/api/assets/secret/{name}")
    data = resp.data
    if isinstance(data, dict):
        return str(data.get("value") or "")
    return str(data or "")


def get_credential(name: str) -> dict[str, str]:
    """Fetch a credential asset and return a dict with username and encrypted password."""
    require_bv_run()
    from bv.orchestrator.client import OrchestratorClient
    client = OrchestratorClient()
    resp = client.request("GET", f"/api/assets/credential/{name}")
    data = resp.data
    return {
        "username": str(data.get("username") or ""),
        "password": str(data.get("password") or "")  # encrypted
    }


def set_asset(name: str, value: str | int | bool) -> None:
    """Update a basic asset value by name."""
    require_bv_run()
    from bv.orchestrator.client import OrchestratorClient
    client = OrchestratorClient()
    client.request("PUT", f"/api/assets/name/{name}", json={"value": value})


def set_secret(name: str, encrypted_value: str) -> None:
    """Update a secret asset with an already encrypted value."""
    require_bv_run()
    from bv.orchestrator.client import OrchestratorClient
    client = OrchestratorClient()
    client.request("PUT", f"/api/assets/secret/{name}", json={"value": encrypted_value})


def set_credential(name: str, username: str, encrypted_password: str) -> None:
    """Update a credential asset with username and an already encrypted password."""
    require_bv_run()
    from bv.orchestrator.client import OrchestratorClient
    client = OrchestratorClient()
    client.request(
        "PUT", 
        f"/api/assets/credential/{name}", 
        json={"username": username, "password": encrypted_password}
    )
