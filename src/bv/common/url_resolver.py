"""URL resolution utilities for Bot Velocity platform (canonical tenant URLs).

This module provides a single source of truth for URL resolution across
all Bot Velocity components using the *canonical* base URL shape:

    https://{host}/{tenant}/orchestrator_/

CONTRACT PARITY: This module mirrors bv-runtime.url_resolver and
bv-runner.url_resolver exactly.  All three components MUST agree on
URL semantics.

Key rules:
- There is only **one** base URL (no /api split).
- The URL MUST include the tenant segment and end with /orchestrator_/.
- Folder isolation is logical (context/headers/claims), NOT part of the URL.
- Legacy /api suffixes are stripped during normalization.
"""

from __future__ import annotations

import logging
from urllib.parse import urlparse

logger = logging.getLogger("bv.url_resolver")


class BaseUrlResolver:
    """Resolves the canonical tenant base URL.

    Usage:
        resolver = BaseUrlResolver("https://eu.cloud.com/acme/orchestrator_")
        print(resolver.canonical_base)  # https://eu.cloud.com/acme/orchestrator_
        print(resolver.tenant)          # acme
        print(resolver.api_base)        # https://eu.cloud.com/acme/orchestrator_
        print(resolver.frontend_base)   # https://eu.cloud.com/acme
        print(resolver.resolve_endpoint("runner/heartbeat"))
        # https://eu.cloud.com/acme/orchestrator_/runner/heartbeat

    Backward compatibility:
        # URL with /api suffix is normalized (stripped)
        resolver = BaseUrlResolver("https://eu.cloud.com/acme/orchestrator_/api")
        # -> canonical: https://eu.cloud.com/acme/orchestrator_

        # URL without /orchestrator_ suffix is auto-completed
        resolver = BaseUrlResolver("https://eu.cloud.com/acme")
        # -> canonical: https://eu.cloud.com/acme/orchestrator_
    """

    def __init__(self, canonical_url: str) -> None:
        """Initialize the resolver with the canonical orchestrator URL.

        Args:
            canonical_url: Must include tenant path segment.
                Ideally ends with /orchestrator_/.
                If /orchestrator_/ is missing, it is appended automatically
                and a warning is logged.

        Raises:
            ValueError: If the URL is empty, missing a scheme/host,
                        or missing the tenant segment.
        """
        if not canonical_url or not canonical_url.strip():
            raise ValueError("Base URL cannot be empty")
        self._canonical_url, self._tenant = self._normalize_and_extract(canonical_url)

    @staticmethod
    def _normalize_and_extract(url: str) -> tuple[str, str]:
        """Normalize to canonical shape and extract tenant segment."""
        raw = url.strip()

        # Remove legacy suffixes (/api) and trailing slashes
        raw = raw.rstrip("/")
        if raw.lower().endswith("/api"):
            raw = raw[:-4]

        # Ensure orchestrator suffix
        needed_suffix = False
        if not raw.lower().endswith("/orchestrator_"):
            needed_suffix = True
            raw = f"{raw}/orchestrator_"

        parsed = urlparse(raw)
        if not parsed.scheme or not parsed.netloc:
            raise ValueError(f"Invalid URL (missing scheme or host): {url}")

        path_parts = [p for p in parsed.path.split("/") if p]
        if len(path_parts) < 2 or path_parts[-1] != "orchestrator_":
            raise ValueError(
                f"Canonical URL must include '/{{tenant}}/orchestrator_/'. "
                f"Got: {url}"
            )

        tenant = path_parts[-2]
        if not tenant:
            raise ValueError("Tenant segment is required in canonical URL")

        canonical = (
            f"{parsed.scheme}://{parsed.netloc}"
            f"/{'/'.join(path_parts[:-1])}/orchestrator_"
        )

        if needed_suffix:
            logger.warning(
                "Base URL normalized: '%s' -> '%s' "
                "(appended /orchestrator_/ suffix). "
                "Consider using the canonical format directly: "
                "https://<host>/<tenant>/orchestrator_",
                url,
                canonical,
            )

        return canonical, tenant

    @property
    def canonical_base(self) -> str:
        """Canonical base URL including tenant and /orchestrator_/ suffix."""
        return self._canonical_url

    @property
    def tenant(self) -> str:
        """Extracted tenant slug from the canonical URL."""
        return self._tenant

    # api_base is an alias for canonical_base (no /api split).
    @property
    def api_base(self) -> str:
        """API base URL (alias for canonical_base; no /api suffix)."""
        return self._canonical_url

    @property
    def frontend_base(self) -> str:
        """Frontend (SPA) base URL: canonical without /orchestrator_/ suffix.

        Useful for browser redirects (e.g. SDK auth flow).
        Example:
            canonical:  https://eu.cloud.com/acme/orchestrator_
            frontend:   https://eu.cloud.com/acme
        """
        # Strip the trailing /orchestrator_ segment
        if self._canonical_url.endswith("/orchestrator_"):
            return self._canonical_url[: -len("/orchestrator_")]
        return self._canonical_url  # pragma: no cover — defensive

    def resolve_endpoint(self, path: str) -> str:
        """Resolve a full API endpoint URL (relative to canonical base).

        Args:
            path: API path (with or without leading slash).

        Returns:
            Full URL for the API endpoint.

        Example:
            resolver.resolve_endpoint("runner/heartbeat")
            # Returns: https://eu.cloud.com/acme/orchestrator_/runner/heartbeat
        """
        path = path.lstrip("/")
        return f"{self._canonical_url}/{path}"

    def __repr__(self) -> str:
        return (
            f"BaseUrlResolver(canonical_base={self._canonical_url!r}, "
            f"tenant={self._tenant!r})"
        )

    def __str__(self) -> str:
        return self._canonical_url


def normalize_url(url: str) -> str:
    """Convenience function to normalize to canonical base URL."""
    return BaseUrlResolver(url).canonical_base


def derive_api_url(frontend_url: str) -> str:
    """Compatibility helper: returns canonical base (no /api split)."""
    return BaseUrlResolver(frontend_url).api_base
