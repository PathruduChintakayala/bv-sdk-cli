from __future__ import annotations

import os


def require_bv_run() -> None:
    if os.environ.get("BV_SDK_RUN") != "1":
        raise RuntimeError("bv.runtime is only available when running via bv run")
