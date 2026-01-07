from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import bv.auth.context as ctx


def _write_auth(dir_path: Path, *, token: str = "dev-token", username: str = "dev-user") -> None:
    expires = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat().replace("+00:00", "Z")
    payload = {
        "api_url": "http://localhost:8000",
        "ui_url": "http://localhost:8000",
        "access_token": token,
        "expires_at": expires,
        "user": {"id": 1, "username": username},
        "machine_name": "test-machine",
    }
    dir_path.mkdir(parents=True, exist_ok=True)
    (dir_path / "auth.json").write_text(json.dumps(payload), encoding="utf-8")


def test_load_prefers_local_over_robot(monkeypatch, tmp_path: Path) -> None:
    auth_dir = tmp_path / "auth"
    _write_auth(auth_dir)
    monkeypatch.setenv("BV_AUTH_DIR", str(auth_dir))

    monkeypatch.setenv("BV_ORCHESTRATOR_URL", "http://robot.example")
    monkeypatch.setenv("BV_ROBOT_TOKEN", "robot-token")
    monkeypatch.delenv("BV_SDK_RUN", raising=False)

    result = ctx.load_auth_context()

    assert result.access_token == "dev-token"
    assert result.user.username == "dev-user"
    assert not str(result.user.username).startswith("robot:")


def test_can_force_robot_token(monkeypatch, tmp_path: Path) -> None:
    auth_dir = tmp_path / "auth"
    _write_auth(auth_dir)
    monkeypatch.setenv("BV_AUTH_DIR", str(auth_dir))

    monkeypatch.setenv("BV_ORCHESTRATOR_URL", "http://robot.example")
    monkeypatch.setenv("BV_ROBOT_TOKEN", "robot-token")
    monkeypatch.setenv("BV_ROBOT_NAME", "runner1")

    result = ctx.load_auth_context(prefer_robot_tokens=True)

    assert result.access_token == "robot-token"
    assert result.user.username == "robot:runner1"
