from __future__ import annotations

from bv.runtime._guard import require_bv_run
from bv.orchestrator import queues as _queues


def list():
    require_bv_run()
    return [q.name for q in _queues.list_queues()]


def put(queue_name: str, payload: dict, reference: str | None = None):
    """Legacy alias for add_queue_item."""
    require_bv_run()
    return add_queue_item(queue_name, payload, reference)


def get(queue_name: str):
    """Legacy alias for get_queue_item."""
    require_bv_run()
    return get_queue_item(queue_name)


def add_queue_item(queue_name: str, payload: dict, reference: str | None = None) -> str:
    """Add a new item to a queue by name."""
    require_bv_run()
    from bv.orchestrator.client import OrchestratorClient
    client = OrchestratorClient()
    body = {
        "queue_name": queue_name,
        "payload": payload,
        "reference": reference
    }
    resp = client.request("POST", "/api/queue-items/add", json=body)
    return str(resp.data.get("id") or "")


def get_queue_item(queue_name: str) -> dict | None:
    """Fetch the next available item from a queue and mark it as IN_PROGRESS."""
    require_bv_run()
    from bv.orchestrator.client import OrchestratorClient
    client = OrchestratorClient()
    resp = client.request("GET", "/api/queue-items/next", params={"queue_name": queue_name})
    if resp.data is None:
        return None
    return dict(resp.data)


def set_queue_item_status(
    item_id: str, 
    status: str, 
    result: dict | None = None, 
    error_message: str | None = None
) -> None:
    """Update the status, result, or error message of a queue item."""
    require_bv_run()
    from bv.orchestrator.client import OrchestratorClient
    client = OrchestratorClient()
    body = {
        "status": status,
        "result": result,
        "error_message": error_message
    }
    client.request("PUT", f"/api/queue-items/{item_id}/status", json=body)
