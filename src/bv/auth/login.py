from __future__ import annotations

import base64
import json
import platform
import time
import webbrowser
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable
from urllib.parse import urlsplit, urlunsplit

import requests

from bv.auth.context import AuthContext, AuthUser


class LoginError(RuntimeError):
    pass


@dataclass(frozen=True)
class LoginResult:
    auth_context: AuthContext
    session_id: str


def _normalize_base_url(url: str) -> str:
    u = (url or "").strip()
    if not u:
        raise LoginError("Orchestrator URL is missing")
    return u.rstrip("/")


def _parse_iso8601(value: str) -> datetime:
    raw = (value or "").strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    dt = datetime.fromisoformat(raw)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _jwt_payload(token: str) -> dict[str, Any] | None:
    try:
        parts = token.split(".")
        if len(parts) < 2:
            return None
        payload_b64 = parts[1]
        # base64url padding
        padded = payload_b64 + "=" * ((4 - len(payload_b64) % 4) % 4)
        decoded = base64.urlsafe_b64decode(padded.encode("utf-8"))
        data = json.loads(decoded.decode("utf-8"))
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def _infer_user_from_token(token: str) -> AuthUser:
    payload = _jwt_payload(token) or {}

    user_id: int | None = None
    for key in ("user_id", "id", "uid", "sub"):
        if payload.get(key) is None:
            continue
        try:
            user_id = int(payload.get(key))
            break
        except Exception:
            pass

    username: str | None = None
    for key in ("username", "preferred_username", "name", "email"):
        if payload.get(key):
            username = str(payload.get(key))
            break

    return AuthUser(id=user_id, username=username)


def open_auth_browser(orchestrator_url: str, session_id: str) -> str:
    base = _normalize_base_url(orchestrator_url)
    # Preserve any existing path/query on ui_url; set fragment to the required route.
    parts = urlsplit(base)
    fragment = f"/sdk-auth?session_id={session_id}"
    target = urlunsplit((parts.scheme, parts.netloc, parts.path, parts.query, fragment))
    try:
        webbrowser.open(target)
    except Exception:
        # Still return the URL so the caller can print it.
        pass
    return target


def start_auth_session(api_url: str, machine_name: str) -> tuple[str, bool]:
    base = _normalize_base_url(api_url)
    start_url = f"{base}/api/sdk/auth/start"

    body = {
        "machine_name": machine_name,
        "os": platform.system(),
    }

    try:
        resp = requests.post(start_url, json=body, timeout=15)
    except requests.RequestException as exc:
        raise LoginError(f"Unable to reach Orchestrator at {base}: {exc}") from exc

    if resp.status_code >= 400:
        raise LoginError(f"Auth start failed ({resp.status_code}): {resp.text}")

    try:
        data = resp.json()
    except Exception as exc:
        raise LoginError(f"Orchestrator returned invalid JSON from auth/start: {exc}") from exc

    if not isinstance(data, dict):
        raise LoginError("Orchestrator returned invalid auth/start payload")

    session_id = str(data.get("session_id") or "").strip()
    if not session_id:
        raise LoginError("Orchestrator auth/start did not return session_id")

    reused = False
    for key in ("reused", "reuse", "existing", "already_exists"):
        if isinstance(data.get(key), bool):
            reused = bool(data.get(key))
            break
    # Some backends may return a string status.
    if isinstance(data.get("status"), str) and data.get("status", "").lower() in ("reused", "existing"):
        reused = True

    return session_id, reused


def poll_for_token(
    orchestrator_url: str,
    session_id: str,
    timeout_seconds: int = 300,
    poll_interval_seconds: float = 2.0,
    on_waiting: Callable[[], None] | None = None,
) -> dict[str, Any]:
    base = _normalize_base_url(orchestrator_url)
    status_url = f"{base}/api/sdk/auth/status"

    deadline = time.time() + float(timeout_seconds)
    last_error: str | None = None

    next_wait_message_at = time.time() + 10.0

    while time.time() < deadline:
        now = time.time()
        if on_waiting is not None and now >= next_wait_message_at:
            on_waiting()
            next_wait_message_at = now + 10.0

        try:
            resp = requests.get(status_url, params={"session_id": session_id}, timeout=10)
        except requests.RequestException as exc:
            last_error = str(exc)
            time.sleep(poll_interval_seconds)
            continue

        if resp.status_code == 410:
            raise LoginError("Auth session expired. Run bv auth login again.")

        if resp.status_code in (200, 201):
            try:
                data = resp.json()
            except Exception as exc:
                raise LoginError(f"Orchestrator returned invalid JSON during auth: {exc}") from exc
            if not isinstance(data, dict):
                raise LoginError("Orchestrator returned invalid auth status payload")

            status = str(data.get("status") or "").lower().strip()
            if status == "expired" or bool(data.get("expired") is True):
                raise LoginError("Auth session expired. Run bv auth login again.")

            token = str(data.get("access_token") or "").strip()
            expires_at = str(data.get("expires_at") or "").strip()
            if token and expires_at:
                return data
            # If 200 but pending payload, keep polling.

        elif resp.status_code in (202, 204):
            # Pending.
            pass
        elif resp.status_code == 404:
            # Session may not exist yet or expired.
            last_error = "session not found"
        elif resp.status_code >= 400:
            try:
                detail = resp.text
            except Exception:
                detail = ""
            if "expired" in (detail or "").lower():
                raise LoginError("Auth session expired. Run bv auth login again.")
            raise LoginError(f"Auth failed ({resp.status_code}): {detail}")

        time.sleep(poll_interval_seconds)

    extra = f" Last error: {last_error}" if last_error else ""
    raise LoginError(f"Timed out waiting for interactive login.{extra}")


def interactive_login(
    api_url: str,
    ui_url: str,
    *,
    on_started: Callable[[str, bool, str], None] | None = None,
    on_waiting: Callable[[], None] | None = None,
) -> LoginResult:
    api_base = _normalize_base_url(api_url)
    ui_base = _normalize_base_url(ui_url)

    machine_name = platform.node() or "<unknown>"
    session_id, reused = start_auth_session(api_base, machine_name=machine_name)

    target = open_auth_browser(ui_base, session_id=session_id)
    if on_started is not None:
        on_started(session_id, reused, target)

    data = poll_for_token(api_base, session_id=session_id, on_waiting=on_waiting)

    access_token = str(data.get("access_token") or "").strip()
    expires_at_raw = str(data.get("expires_at") or "").strip()
    if not access_token or not expires_at_raw:
        raise LoginError("Orchestrator auth status did not provide access_token/expires_at")

    expires_at = _parse_iso8601(expires_at_raw)
    user = None
    if isinstance(data.get("user"), dict):
        user_dict = data.get("user")
        uid = user_dict.get("id")
        try:
            uid = int(uid) if uid is not None else None
        except Exception:
            uid = None
        user = AuthUser(id=uid, username=(str(user_dict.get("username")) if user_dict.get("username") else None))

    if user is None or (user.id is None and not user.username):
        user = _infer_user_from_token(access_token)

    machine_name = platform.node() or None

    ctx = AuthContext(
        api_url=api_base,
        ui_url=ui_base,
        access_token=access_token,
        expires_at=expires_at,
        user=user,
        machine_name=machine_name,
    )

    return LoginResult(auth_context=ctx, session_id=session_id)
