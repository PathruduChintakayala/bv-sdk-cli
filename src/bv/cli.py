
from __future__ import annotations

import json
from pathlib import Path
from typing import List, Optional

import typer

from bv.auth.context import AuthError, logout as auth_logout, save_auth_context, try_load_auth_context
from bv.auth.login import LoginError, interactive_login
from bv.orchestrator.assets import get_asset, list_assets
from bv.orchestrator.queues import dequeue, enqueue, list_queues

from bv.services.commands import (
	ValidationResult,
	add_entrypoint,
	build_package,
	init_project,
	list_entrypoints,
	publish_package,
	run_project,
	set_default_entrypoint,
	validate_project,
)


app = typer.Typer(help="CLI for the Bot Velocity RPA & Agentic Platform")
entry_app = typer.Typer(help="Manage project entrypoints")
app.add_typer(entry_app, name="entry")

auth_app = typer.Typer(help="Developer-mode authentication against Orchestrator")
app.add_typer(auth_app, name="auth")

assets_app = typer.Typer(help="Read-only access to Orchestrator Assets (dev mode)")
app.add_typer(assets_app, name="assets")

queues_app = typer.Typer(help="Access Orchestrator Queues (dev mode)")
app.add_typer(queues_app, name="queues")


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


@app.command(help="Initialize a new project (config + venv)")
def init(
	name: Optional[str] = typer.Option(None, "--name", help="Project name (defaults to current folder)"),
	python: Optional[str] = typer.Option(None, help="Python interpreter to use for the venv"),
) -> None:
	init_project(project_name=name, python_executable=python)
	typer.echo("Initialized project config and venv in current directory")


@entry_app.command("add", help="Add an entrypoint definition")
def entry_add(
	name: str = typer.Argument(..., help="Entrypoint name"),
	command: str = typer.Option(..., help="Command to run for this entrypoint"),
	workdir: Optional[Path] = typer.Option(None, help="Working directory (relative to project root)"),
	set_default: bool = typer.Option(False, help="Mark this entrypoint as default"),
	config: Path = typer.Option(Path("bvproject.yaml"), help="Path to bvproject.yaml"),
) -> None:
	add_entrypoint(config_path=config, name=name, command=command, workdir=workdir, set_default=set_default)
	typer.echo(f"Added entrypoint '{name}'")


@entry_app.command("list", help="List entrypoints")
def entry_list(
	config: Path = typer.Option(Path("bvproject.yaml"), help="Path to bvproject.yaml"),
) -> None:
	names = list_entrypoints(config_path=config)
	for name in names:
		typer.echo(name)


@entry_app.command("set-default", help="Set the default entrypoint")
def entry_set_default(
	name: str = typer.Argument(..., help="Entrypoint name to mark as default"),
	config: Path = typer.Option(Path("bvproject.yaml"), help="Path to bvproject.yaml"),
) -> None:
	set_default_entrypoint(config_path=config, name=name)
	typer.echo(f"Default entrypoint set to '{name}'")


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
	include: List[Path] = typer.Option(
		None,
		help="Additional project-relative paths to include (files or folders)",
	),
	dry_run: bool = typer.Option(False, help="Do not write a package, just compute the target path"),
) -> None:
	package_path = build_package(
		config_path=config,
		output=output,
		include=include,
		dry_run=dry_run,
	)
	typer.echo(f"Package ready: {package_path}")


@app.command(help="Publish (finalize) a .bvpackage locally")
def publish(
	package: Optional[Path] = typer.Argument(None, help="Path to an existing .bvpackage; if absent, build first"),
	config: Path = typer.Option(Path("bvproject.yaml"), help="Path to bvproject.yaml for validation/build"),
	output_dir: Path = typer.Option(Path("published"), help="Directory to place the published artifact"),
	include: List[Path] = typer.Option(
		None,
		help="Additional project-relative paths to include during build if build is triggered",
	),
	major: bool = typer.Option(False, "--major", help="Increment MAJOR version"),
	minor: bool = typer.Option(False, "--minor", help="Increment MINOR version"),
	patch: bool = typer.Option(False, "--patch", help="Increment PATCH version (default)"),
	move: bool = typer.Option(False, help="Move instead of copy the artifact into the publish directory"),
	overwrite: bool = typer.Option(False, help="Allow overwriting an existing artifact in the publish directory"),
	dry_run: bool = typer.Option(False, help="Compute targets without copying/moving"),
) -> None:
	selected = [flag for flag, name in ((major, "major"), (minor, "minor"), (patch, "patch")) if flag]
	if len(selected) > 1:
		typer.echo("ERROR: Only one of --major/--minor/--patch may be set")
		raise typer.Exit(code=1)
	bump = "patch"
	if major:
		bump = "major"
	elif minor:
		bump = "minor"
	elif patch:
		bump = "patch"

	destination = publish_package(
		config_path=config,
		package_path=package,
		publish_dir=output_dir,
		include=include,
		move=move,
		overwrite=overwrite,
		bump=bump,
		dry_run=dry_run,
	)
	typer.echo(f"Published to {destination}")


@app.command(help="Run a configured entrypoint locally")
def run(
	entry: Optional[str] = typer.Option(None, "--entry", help="Entrypoint name (defaults to project default)"),
	input: Optional[Path] = typer.Option(None, "--input", help="Path to a JSON file to pass as input"),
	config: Path = typer.Option(Path("bvproject.yaml"), help="Path to bvproject.yaml"),
) -> None:
	try:
		result = run_project(config_path=config, entry_name=entry, input_path=input)
	except Exception as exc:
		typer.echo(f"ERROR: {exc}")
		raise typer.Exit(code=1)

	try:
		text = json.dumps(result, indent=2)
		typer.echo(text)
	except Exception:
		typer.echo(repr(result))
