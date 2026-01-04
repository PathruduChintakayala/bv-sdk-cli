
from __future__ import annotations

import json
import os
import yaml
from pathlib import Path
from typing import List, Optional

import typer

from bv.auth.context import AuthError, logout as auth_logout, save_auth_context, try_load_auth_context
from bv.auth.login import LoginError, interactive_login
from bv.orchestrator.assets import get_asset, list_assets
from bv.orchestrator.queues import dequeue, enqueue, list_queues
from bv.orchestrator.client import OrchestratorClient, OrchestratorError

from bv.services.commands import (
	ValidationResult,
	build_package,
	init_project,
	publish_package,
	run_project,
)

from bv.project.config import ProjectConfigLoader, bump_semver


app = typer.Typer(name="bv", help="CLI for the Bot Velocity RPA & Agentic Platform")
auth_app = typer.Typer(help="Developer-mode authentication against Orchestrator")
app.add_typer(auth_app, name="auth")

assets_app = typer.Typer(help="Read-only access to Orchestrator Assets (dev mode)")
app.add_typer(assets_app, name="assets")

queues_app = typer.Typer(help="Access Orchestrator Queues (dev mode)")
app.add_typer(queues_app, name="queues")

publish_app = typer.Typer(help="Publish packages")
app.add_typer(publish_app, name="publish")


@auth_app.command("login", help="Authenticate this machine for SDK developer mode")
def auth_login(
	api_url: str = typer.Option(..., "--api-url", help="Orchestrator API base URL (e.g. http://127.0.0.1:8000)"),
	ui_url: str = typer.Option(..., "--ui-url", help="Orchestrator UI base URL (e.g. http://localhost:5173)"),
) -> None:
	try:
		def _started(session_id: str, reused: bool, target: str) -> None:
			if reused:
				typer.echo("Reusing existing auth session …")
			typer.echo(f"Opening browser for login: {target}")
			typer.echo(
			"If you are redirected to dashboard after login, ensure the URL still contains "
			"#/sdk-auth?session_id=..."
		)

		def _waiting() -> None:
			typer.echo("Waiting for browser authentication… (open tab if not already)")

		result = interactive_login(api_url=api_url, ui_url=ui_url, on_started=_started, on_waiting=_waiting)
		save_auth_context(result.auth_context)
		username = result.auth_context.user.username or "<unknown>"
		typer.echo(f"Authenticated as {username}. Auth stored in ~/.bv/auth.json")
	except (AuthError, LoginError) as exc:
		typer.echo(f"ERROR: {exc}")
		raise typer.Exit(code=1)


@auth_app.command("status", help="Show current SDK authentication status")
def auth_status() -> None:
	ctx, err = try_load_auth_context()
	if ctx is None:
		typer.echo("Not logged in")
		if err:
			typer.echo(f"Details: {err}")
		raise typer.Exit(code=0)

	expired = ctx.is_expired()
	typer.echo("Logged in" if not expired else "Not logged in (token expired)")
	typer.echo(f"api_url: {ctx.api_url}")
	typer.echo(f"ui_url: {ctx.ui_url}")
	typer.echo(f"expires_at: {ctx.expires_at.isoformat()}")
	typer.echo(f"username: {ctx.user.username or '<unknown>'}")
	typer.echo(f"machine_name: {ctx.machine_name}")


@auth_app.command("logout", help="Delete local SDK authentication")
def auth_logout_cmd() -> None:
	try:
		deleted = auth_logout()
		if deleted:
			typer.echo("Logged out (deleted ~/.bv/auth.json)")
		else:
			typer.echo("Not logged in")
	except Exception as exc:
		typer.echo(f"ERROR: {exc}")
		raise typer.Exit(code=1)


@assets_app.command("list", help="List assets")
def assets_list(
	search: Optional[str] = typer.Option(None, "--search", help="Search assets"),
) -> None:
	try:
		assets = list_assets(search=search)
		payload = [a.to_public_dict() for a in assets]
		typer.echo(json.dumps(payload, indent=2))
	except Exception as exc:
		typer.echo(f"ERROR: {exc}")
		raise typer.Exit(code=1)


@assets_app.command("get", help="Get an asset by name")
def assets_get(
	name: str = typer.Argument(..., help="Asset name"),
) -> None:
	try:
		asset = get_asset(name)
		typer.echo(json.dumps(asset.to_public_dict(), indent=2))
	except Exception as exc:
		typer.echo(f"ERROR: {exc}")
		raise typer.Exit(code=1)


@queues_app.command("list", help="List queues")
def queues_list() -> None:
	try:
		qs = list_queues()
		typer.echo(json.dumps([{"name": q.name} for q in qs], indent=2))
	except Exception as exc:
		typer.echo(f"ERROR: {exc}")
		raise typer.Exit(code=1)


@queues_app.command("put", help="Enqueue a queue item")
def queues_put(
	queue_name: str = typer.Argument(..., help="Queue name"),
	input: Path = typer.Option(..., "--input", help="Path to JSON payload"),
) -> None:
	try:
		raw = input.read_bytes().decode("utf-8-sig")
		payload = json.loads(raw)
		if not isinstance(payload, dict):
			raise ValueError("Input JSON must be an object (mapping)")
		result = enqueue(queue_name, payload)
		typer.echo(json.dumps(result, indent=2) if result is not None else "null")
	except Exception as exc:
		typer.echo(f"ERROR: {exc}")
		raise typer.Exit(code=1)


@queues_app.command("get", help="Dequeue the next available item")
def queues_get(
	queue_name: str = typer.Argument(..., help="Queue name"),
) -> None:
	try:
		item = dequeue(queue_name)
		typer.echo(json.dumps(item, indent=2) if item is not None else "null")
	except Exception as exc:
		typer.echo(f"ERROR: {exc}")
		raise typer.Exit(code=1)


@app.command(help="Initialize a new project in the current directory (minimal: bvproject.yaml + main.py)")
def init(
	name: str = typer.Argument(None, help="Project name for bvproject.yaml (defaults to current directory name)"),
	python_version: str = typer.Option("3.8", "--python-version", help="Python version to record in bvproject.yaml"),
	keep_main: bool = typer.Option(False, "--keep-main", help="Do not overwrite existing main.py"),
) -> None:
	import os
	# Use current directory name if project name not provided
	if name is None:
		name = Path(os.getcwd()).name
		if not name or name == ".":
			raise typer.BadParameter("Cannot determine project name from current directory. Please provide project name as argument: bv init <project-name>")
	
	try:
		init_project(project_name=name, python_version=python_version, keep_main=keep_main)
		typer.echo(f"Initialized project '{name}' in current directory")
		typer.echo(f"Created bvproject.yaml, main.py, and dist/ folder")
		typer.echo(f"\nNext steps:")
		typer.echo(f"1. Run 'bv build' to generate requirements.lock")
		typer.echo(f"2. Install dependencies: pip install -r requirements.lock")
	except ValueError as e:
		typer.echo(f"ERROR: {e}")
		raise typer.Exit(code=1)


@app.command(help="Validate project configuration")
def validate(
	config: Path = typer.Option(Path("bvproject.yaml"), help="Path to bvproject.yaml"),
	project_root: Path = typer.Option(Path("."), help="Project root for resolving paths"),
) -> None:
	result: ValidationResult = validate_project(config_path=config, project_root=project_root)
	if not result.ok:
		for err in result.errors:
			typer.echo(f"ERROR: {err}")
		raise typer.Exit(code=1)
	for warn in result.warnings:
		typer.echo(f"WARN: {warn}")
	typer.echo("Project configuration is valid.")


@app.command(help="Build a .bvpackage from the project")
def build(
	config: Path = typer.Option(Path("bvproject.yaml"), help="Path to bvproject.yaml"),
	output: Path = typer.Option(None, help="Destination .bvpackage path (default: dist/<name>-<version>.bvpackage)"),
	dry_run: bool = typer.Option(False, help="Do not write a package, just compute the target path"),
) -> None:
	package_path = build_package(
		config_path=config,
		output=output,
		dry_run=dry_run,
	)
	typer.echo(f"Package ready: {package_path}")



@publish_app.command("local", help="Publish (finalize) a .bvpackage locally with validation + lock generation")
def publish_local(
	config: Path = typer.Option(Path("bvproject.yaml"), help="Path to bvproject.yaml for validation/build"),
	output_dir: Path = typer.Option(Path("published"), help="Directory to place the published artifact"),
	dry_run: bool = typer.Option(False, help="Compute targets without copying/moving"),
	major: bool = typer.Option(False, "--major", help="Bump major version"),
	minor: bool = typer.Option(False, "--minor", help="Bump minor version"),
	patch: bool = typer.Option(False, "--patch", help="Bump patch version"),
) -> None:
	bump = "patch"
	if major: bump = "major"
	elif minor: bump = "minor"

	try:
		destination = publish_package(
			config_path=config,
			publish_dir=output_dir,
			dry_run=dry_run,
			bump=bump,
		)
	except Exception as exc:
		typer.echo(f"ERROR: {exc}")
		raise typer.Exit(code=1)
	typer.echo(f"Published to {destination}")


@publish_app.command("orchestrator", help="Publish a .bvpackage to BV Orchestrator")
def publish_orchestrator(
	config: Path = typer.Option(Path("bvproject.yaml"), help="Path to bvproject.yaml"),
	major: bool = typer.Option(False, "--major", help="Bump major version"),
	minor: bool = typer.Option(False, "--minor", help="Bump minor version"),
	patch: bool = typer.Option(False, "--patch", help="Bump patch version"),
) -> None:
	bump = "patch"
	if major: bump = "major"
	elif minor: bump = "minor"

	# 1) Load project metadata (fail fast)
	try:
		cfg = ProjectConfigLoader(config.resolve()).load()
	except FileNotFoundError:
		typer.echo(f"ERROR: bvproject.yaml is missing at {config}")
		raise typer.Exit(code=1)
	except Exception as exc:
		typer.echo(f"ERROR: {exc}")
		raise typer.Exit(code=1)

	# 1.5) Bump version
	try:
		next_version = bump_semver(cfg.version, bump)
		cfg.version = next_version
		# Write back to bvproject.yaml
		with config.open("w", encoding="utf-8") as handle:
			yaml.safe_dump(cfg.to_mapping(), handle, sort_keys=False)
		typer.echo(f"Bumped version to {next_version}")
	except Exception as exc:
		typer.echo(f"ERROR: Failed to bump version: {exc}")
		raise typer.Exit(code=1)

	# 2) Build the package using new minimal builder
	try:
		# Generate requirements.lock
		from bv.tools.lock_generator import RequirementsLockGenerator
		RequirementsLockGenerator().generate(str(config.resolve().parent), cfg.dependencies or [])

		package_path = build_package(
			config_path=config,
			output=None,
			dry_run=False,
		)
	except Exception as exc:
		typer.echo(f"ERROR: {exc}")
		raise typer.Exit(code=1)

	client = OrchestratorClient()

	# 3) Preflight
	try:
		resp = client.request(
			"POST",
			"/api/packages/preflight",
			json={"name": cfg.name, "version": cfg.version},
		)
	except OrchestratorError as exc:
		typer.echo(f"ERROR: {exc}")
		raise typer.Exit(code=1)

	data = resp.data
	if not isinstance(data, dict):
		typer.echo("ERROR: Preflight returned an unexpected response")
		raise typer.Exit(code=1)

	if not bool(data.get("can_publish")):
		reason = data.get("reason") or data.get("message") or data.get("detail") or "Publish rejected"
		typer.echo(str(reason))
		raise typer.Exit(code=1)

	# 4) Upload
	try:
		with package_path.open("rb") as handle:
			files = {"file": (package_path.name, handle, "application/octet-stream")}
			client.request("POST", "/api/packages/upload", files=files)
	except OrchestratorError as exc:
		typer.echo(f"ERROR: Failed to upload package: {exc}")
		raise typer.Exit(code=1)
	except Exception as exc:
		typer.echo(f"ERROR: Failed to upload package: {exc}")
		raise typer.Exit(code=1)

	# 5) Success output
	typer.echo(f"Published {cfg.name}@{cfg.version} to {client.base_url}")


@app.command(help="Run a configured entrypoint locally")
def run(
	config: Path = typer.Option(Path("bvproject.yaml"), help="Path to bvproject.yaml"),
	entry: Optional[str] = typer.Option(None, "--entry", help="Entrypoint name to run"),
) -> None:
	try:
		result = run_project(config_path=config, entrypoint_name=entry)
	except Exception as exc:
		typer.echo(f"ERROR: {exc}")
		raise typer.Exit(code=1)

	try:
		text = json.dumps(result, indent=2)
		typer.echo(text)
	except Exception:
		typer.echo(repr(result))


if __name__ == "__main__":
	app(prog_name="bv")
