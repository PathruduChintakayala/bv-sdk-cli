
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import requests

from bv.auth.context import AuthError, AuthContext, require_auth


class OrchestratorError(RuntimeError):
	pass


@dataclass(frozen=True)
class OrchestratorResponse:
	status_code: int
	data: Any


class OrchestratorClient:
	"""Authenticated HTTP client for BV Orchestrator (developer-mode SDK).

	This client is intentionally limited to dev-only read/write operations needed
	for assets and queues access.
	"""

	def __init__(
		self,
		*,
		auth_context: AuthContext | None = None,
		timeout_seconds: int = 20,
	) -> None:
		self._timeout_seconds = timeout_seconds
		self._ctx = auth_context

	def _auth(self) -> AuthContext:
		if self._ctx is None:
			self._ctx = require_auth()
		return self._ctx

	@property
	def base_url(self) -> str:
		return self._auth().api_url.rstrip("/")

	def request(self, method: str, path: str, *, params: dict | None = None, json: Any = None) -> OrchestratorResponse:
		try:
			ctx = self._auth()
		except AuthError as exc:
			raise OrchestratorError(str(exc)) from exc
		url = f"{ctx.api_url.rstrip('/')}/{path.lstrip('/')}"
		headers = {
			"Authorization": f"Bearer {ctx.access_token}",
			"Accept": "application/json",
		}

		try:
			resp = requests.request(
				method.upper(),
				url,
				headers=headers,
				params=params,
				json=json,
				timeout=self._timeout_seconds,
			)
		except requests.RequestException as exc:
			raise OrchestratorError(f"Unable to reach Orchestrator at {ctx.api_url}: {exc}") from exc

		if resp.status_code == 401:
			raise OrchestratorError("Not authenticated. Run bv auth login")
		if resp.status_code == 403:
			raise OrchestratorError("Permission denied")

		content_type = resp.headers.get("Content-Type", "")
		data: Any
		if "application/json" in content_type:
			try:
				data = resp.json()
			except Exception:
				data = resp.text
		else:
			data = resp.text

		if resp.status_code >= 400:
			message = None
			if isinstance(data, dict):
				message = data.get("detail") or data.get("message") or data.get("error")
			if not message:
				message = data if isinstance(data, str) else repr(data)
			raise OrchestratorError(f"Orchestrator error {resp.status_code}: {message}")

		return OrchestratorResponse(status_code=resp.status_code, data=data)
