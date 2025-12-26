from __future__ import annotations

from bv.runtime._guard import require_bv_run
from bv.orchestrator import assets as _assets


def get(name: str):
    """Return an asset value by name.

    Fails fast if not authenticated or not running via `bv run`.
    """
    require_bv_run()
    asset = _assets.get_asset(name)
    return asset.value
