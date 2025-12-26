from __future__ import annotations

from bv.runtime._guard import require_bv_run
from bv.orchestrator import queues as _queues


def list():
    require_bv_run()
    return [q.name for q in _queues.list_queues()]


def put(queue_name: str, payload: dict):
    require_bv_run()
    return _queues.enqueue(queue_name, payload)


def get(queue_name: str):
    require_bv_run()
    return _queues.dequeue(queue_name)
