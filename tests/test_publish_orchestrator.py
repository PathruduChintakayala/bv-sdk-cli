from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

import bv.cli as cli
import bv.orchestrator.client as orch_client


class _FakeResp:
    def __init__(
        self,
        *,
        status_code: int,
        json_data: Any = None,
        text: str = "",
        headers: dict[str, str] | None = None,
    ):
        self.status_code = status_code
        self._json_data = json_data
        self.text = text
        self.headers = headers or {"Content-Type": "application/json"}

    def json(self) -> Any:
        if self._json_data is None:
            raise ValueError("No JSON")
        return self._json_data


def _write_auth(
    tmp: Path,
    *,
    base_url: str = "http://127.0.0.1:8000/default/orchestrator_",
) -> None:
    """Write auth file with canonical base_url.

    base_url must include tenant segment and /orchestrator_/ suffix.
    Example: http://127.0.0.1:8000/default/orchestrator_
    """
    expires = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat().replace("+00:00", "Z")
    payload = {
        "base_url": base_url,
        "access_token": "token123",
        "expires_at": expires,
        "user": {"id": 1, "username": "dev"},
        "machine_name": "test",
    }
    (tmp / "auth.json").write_text(json.dumps(payload), encoding="utf-8")


def _write_bvproject(tmp: Path, *, version: str = "1.2.3") -> None:
    (tmp / "bvproject.yaml").write_text(
        "\n".join(
            [
                "name: demo-automation",
                f"version: {version}",
                "entrypoints:",
                "- name: main",
                "  command: main:main",
                "  default: true",
                "venv_dir: .venv",
                "",
            ]
        ),
        encoding="utf-8",
    )


def test_publish_stops_if_preflight_rejects(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    runner = CliRunner()

    with runner.isolated_filesystem(temp_dir=tmp_path) as wd:
        wd_path = Path(wd)
        _write_bvproject(wd_path)

        auth_dir = wd_path / "auth"
        auth_dir.mkdir(parents=True, exist_ok=True)
        _write_auth(auth_dir)

        built_pkg = wd_path / "dist" / "demo-automation-1.2.3.bvpackage"
        built_pkg.parent.mkdir(parents=True, exist_ok=True)
        built_pkg.write_bytes(b"zip")

        def _fake_build_package(*, config_path, output, include, dry_run):
            return built_pkg

        monkeypatch.setattr(cli, "build_package", _fake_build_package)

        calls: list[tuple[str, str]] = []

        def _fake_request(method: str, url: str, **kwargs):
            calls.append((method, url))
            if "/packages/preflight" in url:
                return _FakeResp(status_code=200, json_data={"can_publish": False, "reason": "already exists"})
            if "/packages/upload" in url:
                return _FakeResp(status_code=200, json_data={"ok": True})
            return _FakeResp(status_code=404, json_data={"detail": "not found"})

        monkeypatch.setattr(orch_client.requests, "request", _fake_request)
        monkeypatch.setenv("BV_AUTH_DIR", str(auth_dir))

        result = runner.invoke(cli.app, ["publish", "orchestrator"], catch_exceptions=False)

        assert result.exit_code == 1
        assert "already exists" in result.output
        assert any("/packages/preflight" in p for _, p in calls)
        assert not any("/packages/upload" in p for _, p in calls)


def test_publish_uploads_only_after_successful_preflight(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    runner = CliRunner()

    with runner.isolated_filesystem(temp_dir=tmp_path) as wd:
        wd_path = Path(wd)
        _write_bvproject(wd_path)

        auth_dir = wd_path / "auth"
        auth_dir.mkdir(parents=True, exist_ok=True)
        _write_auth(auth_dir)

        built_pkg = wd_path / "dist" / "demo-automation-1.2.3.bvpackage"
        built_pkg.parent.mkdir(parents=True, exist_ok=True)
        built_pkg.write_bytes(b"zip")

        def _fake_build_package(*, config_path, output, include, dry_run):
            return built_pkg

        monkeypatch.setattr(cli, "build_package", _fake_build_package)

        calls: list[str] = []

        def _fake_request(method: str, url: str, **kwargs):
            calls.append(url)
            if "/packages/preflight" in url:
                body = kwargs.get("json")
                assert body == {"name": "demo-automation", "version": "1.2.3"}
                return _FakeResp(status_code=200, json_data={"can_publish": True})
            if "/packages/upload" in url:
                files = kwargs.get("files")
                assert files and "file" in files
                return _FakeResp(status_code=200, json_data={"ok": True})
            return _FakeResp(status_code=404, json_data={"detail": "not found"})

        monkeypatch.setattr(orch_client.requests, "request", _fake_request)
        monkeypatch.setenv("BV_AUTH_DIR", str(auth_dir))

        result = runner.invoke(cli.app, ["publish", "orchestrator"], catch_exceptions=False)

        assert result.exit_code == 0
        assert "Published demo-automation@1.2.3" in result.output
        assert "/packages/preflight" in calls[-2]
        assert "/packages/upload" in calls[-1]


def test_publish_auth_error_handled(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    runner = CliRunner()

    with runner.isolated_filesystem(temp_dir=tmp_path) as wd:
        wd_path = Path(wd)
        _write_bvproject(wd_path)

        built_pkg = wd_path / "dist" / "demo-automation-1.2.3.bvpackage"
        built_pkg.parent.mkdir(parents=True, exist_ok=True)
        built_pkg.write_bytes(b"zip")

        def _fake_build_package(*, config_path, output, include, dry_run):
            return built_pkg

        monkeypatch.setattr(cli, "build_package", _fake_build_package)

        auth_dir = wd_path / "auth"
        auth_dir.mkdir(parents=True, exist_ok=True)
        monkeypatch.setenv("BV_AUTH_DIR", str(auth_dir))

        result = runner.invoke(cli.app, ["publish", "orchestrator"], catch_exceptions=False)

        assert result.exit_code == 1
        assert "Not authenticated" in result.output


def test_no_upload_happens_on_upload_failure(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    runner = CliRunner()

    with runner.isolated_filesystem(temp_dir=tmp_path) as wd:
        wd_path = Path(wd)
        _write_bvproject(wd_path)

        auth_dir = wd_path / "auth"
        auth_dir.mkdir(parents=True, exist_ok=True)
        _write_auth(auth_dir)

        built_pkg = wd_path / "dist" / "demo-automation-1.2.3.bvpackage"
        built_pkg.parent.mkdir(parents=True, exist_ok=True)
        built_pkg.write_bytes(b"zip")

        def _fake_build_package(*, config_path, output, include, dry_run):
            return built_pkg

        monkeypatch.setattr(cli, "build_package", _fake_build_package)

        upload_attempts = 0

        def _fake_request(method: str, url: str, **kwargs):
            nonlocal upload_attempts
            if "/packages/preflight" in url:
                return _FakeResp(status_code=200, json_data={"can_publish": True})
            if "/packages/upload" in url:
                upload_attempts += 1
                return _FakeResp(status_code=500, json_data={"detail": "backend exploded"})
            return _FakeResp(status_code=404, json_data={"detail": "not found"})

        monkeypatch.setattr(orch_client.requests, "request", _fake_request)
        monkeypatch.setenv("BV_AUTH_DIR", str(auth_dir))

        result = runner.invoke(cli.app, ["publish", "orchestrator"], catch_exceptions=False)

        assert result.exit_code == 1
        assert upload_attempts == 1
        assert "Failed to upload package" in result.output
        assert "backend exploded" in result.output
