from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from bv.orchestrator.client import OrchestratorClient


@dataclass(frozen=True)
class Queue:
    name: str


def list_queues() -> list[Queue]:
    client = OrchestratorClient()
    resp = client.request("GET", "/api/queues")
    data = resp.data

    if isinstance(data, dict) and isinstance(data.get("items"), list):
        items = data.get("items")
    elif isinstance(data, list):
        items = data
    else:
        items = []

    queues: list[Queue] = []
    for item in items:
        if isinstance(item, str):
            queues.append(Queue(name=item))
            continue
        if not isinstance(item, dict):
            continue
        name = item.get("name") or item.get("queue_name")
        if name:
            queues.append(Queue(name=str(name)))

    return queues


def enqueue(queue_name: str, payload: dict) -> Any:
    if not queue_name:
        raise ValueError("queue_name is required")
    if not isinstance(payload, dict):
        raise ValueError("payload must be a JSON object")

    client = OrchestratorClient()
    body = {"queue_name": queue_name, "payload": payload}
    resp = client.request("POST", "/api/queue-items", json=body)
    return resp.data


def dequeue(queue_name: str) -> dict | None:
    if not queue_name:
        raise ValueError("queue_name is required")

    client = OrchestratorClient()

    # Try a "next" endpoint first.
    try:
        resp = client.request("GET", "/api/queue-items/next", params={"queue_name": queue_name})
        data = resp.data
        if data in (None, "", []):
            return None
        if isinstance(data, dict) and data.get("item") is not None:
            return data.get("item")
        if isinstance(data, dict):
            return data
        return None
    except Exception:
        pass

    # Fallback: plain list endpoint.
    resp = client.request("GET", "/api/queue-items", params={"queue_name": queue_name, "limit": 1})
    data = resp.data
    if isinstance(data, dict) and isinstance(data.get("items"), list):
        items = data.get("items")
        return items[0] if items else None
    if isinstance(data, list):
        return data[0] if data else None
    return None
