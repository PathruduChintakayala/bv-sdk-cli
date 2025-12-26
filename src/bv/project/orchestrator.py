from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


def resolve_orchestrator_url(config_path: Path = Path("bvproject.yaml")) -> str | None:
    """Resolve orchestrator.url from bvproject.yaml without changing config schema.

    Expected structure:

    orchestrator:
      url: http://127.0.0.1:8000
    """
    if not config_path.exists():
        return None

    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    except Exception:
        return None

    if not isinstance(raw, dict):
        return None

    orch: Any = raw.get("orchestrator")
    if not isinstance(orch, dict):
        return None

    url = orch.get("url")
    if url is None:
        return None

    text = str(url).strip()
    return text or None
