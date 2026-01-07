from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Mapping


class AuthError(RuntimeError):
    pass


@dataclass(frozen=True)
class AuthUser:
    id: int | None
    username: str | None


@dataclass(frozen=True)
class AuthMachine:
    name: str | None


@dataclass(frozen=True)
class AuthContext:
    api_url: str
    ui_url: str
    access_token: str
    expires_at: datetime
    user: AuthUser
    machine_name: str

    def is_expired(self) -> bool:
        now = datetime.now(timezone.utc)
        expires = self.expires_at
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        return now >= expires


def _auth_dir() -> Path:
    # Allow overrides for tests/dev tooling.
    override = os.environ.get("BV_AUTH_DIR")
    if override:
        return Path(override).expanduser().resolve()
    return (Path.home() / ".bv").resolve()


def auth_file_path() -> Path:
    return _auth_dir() / "auth.json"


def _parse_iso8601(value: str) -> datetime:
    raw = (value or "").strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    dt = datetime.fromisoformat(raw)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _normalize_base_url(url: str) -> str:
    u = (url or "").strip()
    if not u:
        raise AuthError("Orchestrator URL is missing")
    return u.rstrip("/")


def _atomic_write_json(path: Path, data: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def save_auth_context(ctx: AuthContext) -> None:
    payload: dict[str, Any] = {
        "api_url": _normalize_base_url(ctx.api_url),
        "ui_url": _normalize_base_url(ctx.ui_url),
        "access_token": ctx.access_token,
        "expires_at": ctx.expires_at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        "user": {
            "id": ctx.user.id,
            "username": ctx.user.username,
        },
        "machine_name": ctx.machine_name,
    }
    _atomic_write_json(auth_file_path(), payload)


def _robot_auth_context(env_url: str, env_token: str) -> AuthContext:
    robot_name = os.environ.get("BV_ROBOT_NAME", "unknown")
    return AuthContext(
        api_url=_normalize_base_url(env_url),
        ui_url=_normalize_base_url(env_url), # Best effort
        access_token=env_token,
        expires_at=datetime.now(timezone.utc) + timedelta(days=365), # Long-lived robot token
        user=AuthUser(id=None, username=f"robot:{robot_name}"),
        machine_name=os.environ.get("BV_MACHINE_NAME", "runner-machine"),
    )


def _load_local_auth_file(path: Path) -> AuthContext:
    try:
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
    except Exception as exc:
        raise AuthError(f"Invalid auth file at {path}: {exc}") from exc

    if not isinstance(data, dict):
        raise AuthError(f"Invalid auth file at {path}: expected JSON object")

    # New schema (preferred)
    api_url_raw = data.get("api_url")
    ui_url_raw = data.get("ui_url")

    # Backward compat: older schema used orchestrator_url.
    if api_url_raw is None and data.get("orchestrator_url") is not None:
        api_url_raw = data.get("orchestrator_url")
    if ui_url_raw is None and data.get("orchestrator_url") is not None:
        # Best-effort: in older schema we didn't know ui_url; keep same base.
        ui_url_raw = data.get("orchestrator_url")

    api_url = _normalize_base_url(str(api_url_raw or ""))
    ui_url = _normalize_base_url(str(ui_url_raw or ""))
    access_token = str(data.get("access_token") or "").strip()
    if not access_token:
        raise AuthError("Invalid auth file: missing access_token. Run bv auth login")

    expires_raw = str(data.get("expires_at") or "").strip()
    if not expires_raw:
        raise AuthError("Invalid auth file: missing expires_at. Run bv auth login")

    try:
        expires_at = _parse_iso8601(expires_raw)
    except Exception as exc:
        raise AuthError(f"Invalid auth file: expires_at is not ISO8601: {exc}") from exc

    user = data.get("user") if isinstance(data.get("user"), dict) else {}

    machine_name = data.get("machine_name")
    if machine_name is None and isinstance(data.get("machine"), dict):
        machine_name = data.get("machine", {}).get("name")
    machine_name = str(machine_name) if machine_name is not None else ""
    machine_name = machine_name.strip() or "<unknown>"

    user_id = user.get("id")
    if user_id is not None:
        try:
            user_id = int(user_id)
        except Exception:
            user_id = None

    return AuthContext(
        api_url=api_url,
        ui_url=ui_url,
        access_token=access_token,
        expires_at=expires_at,
        user=AuthUser(
            id=user_id,
            username=(str(user.get("username")) if user.get("username") is not None else None),
        ),
        machine_name=machine_name,
    )


def load_auth_context(*, prefer_robot_tokens: bool | None = None) -> AuthContext:
    """
    Resolve auth context with sensible priority.

    Priority:
    1) Robot token via env when explicitly preferred (BV_SDK_RUN=1 or prefer_robot_tokens=True)
    2) Local developer auth file (~/.bv/auth.json)
    3) Robot token via env as a fallback when no file is present
    """

    env_url = os.environ.get("BV_ORCHESTRATOR_URL")
    env_token = os.environ.get("BV_ROBOT_TOKEN")
    robot_available = bool(env_url and env_token)

    prefer_robot = bool(prefer_robot_tokens) if prefer_robot_tokens is not None else (os.environ.get("BV_SDK_RUN") == "1")

    if prefer_robot and robot_available:
        return _robot_auth_context(env_url, env_token)

    # Check local auth file (Developer mode)
    path = auth_file_path()
    if path.exists():
        return _load_local_auth_file(path)

    # Fallback to robot token when no developer auth is present
    if robot_available:
        return _robot_auth_context(env_url, env_token)

    raise AuthError("Not authenticated. Run bv auth login")


def try_load_auth_context() -> tuple[AuthContext | None, str | None]:
    """Best-effort loader for diagnostics.

    Returns (context, error). Does not raise for common problems.
    """
    try:
        ctx = load_auth_context()
        return ctx, None
    except Exception as exc:
        return None, str(exc)


def logout() -> bool:
    """Delete the local auth file.

    Returns True if a file was deleted, False if it did not exist.
    """
    path = auth_file_path()
    if not path.exists():
        return False
    path.unlink()
    return True


def require_auth(*, prefer_robot_tokens: bool | None = None) -> AuthContext:
    """Load and validate the auth context.

    prefer_robot_tokens allows callers (e.g. runtime) to explicitly prefer
    robot tokens supplied via environment variables. CLI commands should rely
    on the default, which favors local developer auth when available.
    """
    ctx = load_auth_context(prefer_robot_tokens=prefer_robot_tokens)
    if ctx.is_expired():
        raise AuthError("Token expired. Run bv auth login")
    return ctx


# Backward-compatible alias for existing internal usage.
def get_auth_context(*, prefer_robot_tokens: bool | None = None) -> AuthContext:
    return require_auth(prefer_robot_tokens=prefer_robot_tokens)
