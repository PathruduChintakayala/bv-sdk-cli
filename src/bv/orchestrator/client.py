from __future__ import annotations
import logging
import re
from dataclasses import dataclass
from typing import Any, Dict, Optional, List
import httpx
from bv.auth.context import AuthError, AuthContext, require_auth


class OrchestratorError(RuntimeError):
    pass


def _redact_tokens(text: str) -> str:
    """Redact potential tokens from error messages.
    
    Removes JWT-like strings and long hex strings that may be tokens.
    This prevents accidental token leakage in error logs.
    """
    if not text:
        return text
    # Redact JWT-like strings (header.payload.signature)
    text = re.sub(r'eyJ[A-Za-z0-9_-]+\.eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+', '[REDACTED]', text)
    # Redact hex tokens (32+ chars, typical for API tokens)
    text = re.sub(r'[a-f0-9]{32,}', '[REDACTED]', text, flags=re.IGNORECASE)
    return text

@dataclass(frozen=True)
class OrchestratorResponse:
    status_code: int
    data: Any

class OrchestratorClient:
    """Authenticated HTTP client for BV Orchestrator (developer-mode SDK)."""

    def __init__(
        self,
        *,
        auth_context: AuthContext | None = None,
        timeout_seconds: int = 30,
    ) -> None:
        self._timeout_seconds = timeout_seconds
        self._ctx = auth_context
        self._client = httpx.Client(timeout=float(timeout_seconds))

    def _auth(self) -> AuthContext:
        if self._ctx is None:
            self._ctx = require_auth()
        return self._ctx

    @property
    def base_url(self) -> str:
        """Get the canonical API base URL for requests.
        
        Returns the canonical /{tenant}/orchestrator_/ URL.
        AuthContext.api_url is derived from base_url using BaseUrlResolver.
        """
        return self._auth().api_url.rstrip("/")

    def _headers(self) -> Dict[str, str]:
        ctx = self._auth()
        headers = {
            "Accept": "application/json",
        }
        if ctx.user and ctx.user.username and ctx.user.username.startswith("robot:"):
            headers["X-Robot-Token"] = ctx.access_token
        else:
            headers["Authorization"] = f"Bearer {ctx.access_token}"
        return headers

    def request(
        self,
        method: str,
        path: str,
        *,
        params: dict | None = None,
        json: Any = None,
        data: Any = None,
        files: Any = None,
    ) -> OrchestratorResponse:
        url = f"{self.base_url}/{path.lstrip('/')}"
        
        try:
            resp = self._client.request(
                method.upper(),
                url,
                headers=self._headers(),
                params=params,
                json=json,
                data=data,
                files=files,
            )
        except httpx.RequestError as exc:
            raise OrchestratorError(f"Unable to reach Orchestrator at {self.base_url}: {exc}") from exc

        if resp.status_code == 401:
            raise OrchestratorError("Not authenticated. Run bv auth login")
        if resp.status_code == 403:
            # Try to extract detailed permission error message
            try:
                error_data = resp.json()
                detail = error_data.get("detail") if isinstance(error_data, dict) else None
                if detail:
                    # Redact potential tokens from error detail
                    detail = _redact_tokens(str(detail))
                    raise OrchestratorError(f"Permission denied: {detail}")
            except OrchestratorError:
                raise
            except Exception:
                pass
            raise OrchestratorError("Permission denied")

        data_out: Any
        try:
            data_out = resp.json()
        except Exception:
            data_out = resp.text

        if resp.status_code >= 400:
            message = None
            if isinstance(data_out, dict):
                message = data_out.get("detail") or data_out.get("message") or data_out.get("error")
            if not message:
                message = data_out if isinstance(data_out, str) else repr(data_out)
            # Redact potential tokens from error messages
            if isinstance(message, str):
                message = _redact_tokens(message)
            raise OrchestratorError(f"Orchestrator error {resp.status_code}: {message}")

        return OrchestratorResponse(status_code=resp.status_code, data=data_out)
