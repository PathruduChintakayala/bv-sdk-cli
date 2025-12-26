from __future__ import annotations

from typing import Any

def main(input: dict[str, Any] | None = None) -> dict[str, Any]:
    data = input or {}
    name = str(data.get("name", "World"))
    return {"result": f"Hello {name}"}
