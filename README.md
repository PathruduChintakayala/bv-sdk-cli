# bv-sdk-cli

Typer-based CLI (Python 3.11+) for local-only, deterministic Python automations.

Key properties:

- Local-first and deterministic for build/publish/run behavior.
- Optional developer-mode Orchestrator integration (interactive user auth) for local development.
- The automation contract is `bvproject.yaml`.
- `pyproject.toml` is used only for Python dependency management.
- Project root is treated as the Python import root (no `src/` layout is assumed).

## Project layout (key modules)

- `src/bv/cli.py`: Typer commands (`init`, `entry …`, `validate`, `run`, `build`, `publish`)
- `src/bv/project/config.py`: `bvproject.yaml` loader, schema, SemVer validation, SemVer bump
- `src/bv/entrypoints/registry.py`: entrypoint management + import validation (temporarily adds project root to `sys.path`)
- `src/bv/venv/manager.py`: project-scoped virtualenv creation and `pip freeze`
- `src/bv/packaging/builder.py`: deterministic `.bvpackage` creation (manifest, entry-points, requirements.lock)
- `src/bv/packaging/bvpackage_validator.py`: BV Package Contract v1 validator
- `docs/bv-package-contract-v1.md`: BV Package Contract v1 (authoritative)

## Configuration responsibilities

### bvproject.yaml (source of truth)

The SDK reads these fields from `bvproject.yaml`:

- `name` (project name)
- `version` (SemVer)
- `entrypoints` (commands and default)
- `venv_dir` (virtual environment directory, typically `.venv`)

This file is required for validate/build/publish/run.

Minimal example:

```yaml
name: demo-automation
version: 0.0.0

entrypoints:
	- name: main
		command: main:main
		default: true

venv_dir: .venv
```

### pyproject.toml (dependencies only)

`pyproject.toml` is generated/used only for dependency management. It MUST NOT contain `name` or `version`.

Generated minimal structure:

```toml
[project]
requires-python = ">=3.11"
dependencies = []
```

### bindings.json (reserved / no runtime behavior)

`bindings.json` is generated for future extensibility.

- It is NOT validated.
- It is NOT required for validate/build/run.
- It may be empty.

## Quick start (local workflow)

1) Install the CLI locally (editable):

- `pip install -e .`

2) Initialize a project in an empty folder:

- `bv init [--name <project-name>] [--python <python-exe>]`

Behavior:

- Fails if `bvproject.yaml` already exists.
- Creates `.venv/` (project-scoped venv) and `dist/`.
- Generates only: `main.py`, `entry-points.json`, `bindings.json`, `bvproject.yaml`, `pyproject.toml`.
- Does NOT create `src/` or `tests/`.
- Initial version is always `0.0.0`.
- Project name is resolved as:
	- if `--name` provided: use it
	- else: use the current directory name (`Path.cwd().name`)

3) Validate configuration and entrypoints:

- `bv validate`

This checks that:

- `bvproject.yaml` exists
- `version` is valid SemVer
- at least one entrypoint exists
- exactly one entrypoint is marked `default`
- each entrypoint’s `command` is importable as `module:function` from the project root

4) Run locally (in-process):

- `bv run [--entry <name>] [--input <json-file>]`

Rules:

- Uses project root as import root (temporarily inserts it into `sys.path`).
- Does not switch virtual environments.
- Does not spawn subprocesses.
- Does not perform any network calls unless your automation imports and uses `bv.runtime` (developer-mode Orchestrator access).

Input handling:

- If `--input` is omitted: calls the function with `{}` (or no args, depending on signature).
- If `--input` is provided: parses JSON into a dict and passes that as the single argument.
- The input JSON must be an object (mapping). Empty input is allowed.

Output handling:

- Prints returned value to stdout as JSON when possible, otherwise prints `repr(result)`.

## Developer-mode Orchestrator access (Auth, Assets, Queues)

The SDK supports a **developer-only** authentication mode that lets you call Orchestrator APIs while developing locally.

This is explicitly NOT runner execution, NOT unattended automation, and NOT production auth.

### Strict boundaries

This SDK auth mode MUST NOT be used to:

- Register robots
- Send machine heartbeats
- Execute jobs
- Call runner APIs
- Use robot/service-account tokens

### Login

Authenticate interactively via the browser:

- `bv auth login --api-url http://127.0.0.1:8000 --ui-url http://localhost:5173`

Flow:

1) SDK calls `POST {api-url}/api/sdk/auth/start` (includes machine name)
2) SDK opens `{ui-url}/#/sdk-auth?session_id=...`
3) SDK polls `GET {api-url}/api/sdk/auth/status?session_id=...` every 2 seconds
4) On success, SDK writes `~/.bv/auth.json` and overwrites any existing auth

Timeout: 5 minutes.

Diagnostics:

- The CLI prints the exact URL it opens (never prints tokens).
- While polling, it prints a short message about every ~10 seconds:
	- `Waiting for browser authentication… (open tab if not already)`
- If you are redirected to the dashboard after login, ensure the URL still contains `#/sdk-auth?session_id=...`.
- If the auth session expires, the CLI stops and tells you to run `bv auth login` again.

Session reuse:

- If the backend reuses an existing auth session for the same machine, the CLI prints `Reusing existing auth session …` and continues normally.

### Auth status / logout

- `bv auth status`
	- Shows: logged in / not logged in, `api_url`, `ui_url`, `expires_at`, `username`, `machine_name`
	- Never prints the token
- `bv auth logout`
	- Deletes `~/.bv/auth.json` if present

### Token storage

Auth is stored unencrypted (dev-only) at `~/.bv/auth.json`:

```json
{
	"api_url": "http://127.0.0.1:8000",
	"ui_url": "http://localhost:5173",
	"access_token": "...",
	"expires_at": "ISO8601",
	"user": {
		"id": 1,
		"username": "admin"
	},
	"machine_name": "DEV-HOST-01"
}
```

The CLI must never print the token.

### Assets (read-only)

- `bv assets list [--search TEXT]`
- `bv assets get <name>`

Secret/credential-like assets are masked in CLI output as `"***"`.

### Queues

- `bv queues list`
- `bv queues put <queue-name> --input payload.json`
- `bv queues get <queue-name>`

### Runtime access during `bv run`

During `bv run`, automation code can access assets and queues via:

```python
from bv.runtime import assets, queues

value = assets.get("MY_CONFIG")
item = queues.get("orders")
queues.put("results", {"id": 1})
```

These runtime modules are only available when your code is executed via `bv run`.
They fail fast if used outside of `bv run` or if you are not authenticated.

5) Build a deterministic package:

- `bv build`
- `bv build --dry-run`

Notes:

- `bv build` MUST NOT change the version.
- Build generates `requirements.lock` from the project’s venv as part of packaging.

6) Publish locally (auto-increments version):

- `bv publish local` (defaults to PATCH bump)
- `bv publish local --major`
- `bv publish local --minor`
- `bv publish local --patch`

Publish behavior:

- Bumps the version in `bvproject.yaml` (unless `--dry-run`).
- Persists the bumped version first, then builds (if needed) using the bumped version.
- Copies (or moves) the artifact into `./published/<name>/<version>/`.
- Never overwrites an existing artifact unless `--overwrite` is passed.

7) Publish to Orchestrator (developer-mode, safe preflight):

- `bv publish orchestrator`
	- Reads `bvproject.yaml` (name + SemVer version)
	- Builds a deterministic `.bvpackage` using the existing `bv build` logic
	- Calls `POST /api/packages/preflight` and stops if rejected
	- Uploads the package via `POST /api/packages/upload` (multipart/form-data)
	- Prints: `Published <name>@<version> to <orchestrator-url>`

Notes:
- You must be authenticated first: `bv auth login ...`
- Orchestrator is the final authority for publish validation.
- The SDK does not retry uploads automatically.

## Entrypoints

Entrypoints are defined in `bvproject.yaml` under `entrypoints`.

Each entrypoint must have:

- `name`: unique identifier
- `command`: in `module:function` format (example: `main:main`)
- `default`: exactly one entrypoint must be `default: true`

Entrypoint management commands:

- `bv entry add <NAME> --command module:function [--workdir PATH] [--set-default]`
- `bv entry list`
- `bv entry set-default <NAME>`

## What gets packaged

`bv build` produces a `.bvpackage` that includes:

- `main.py`
- `entry-points.json`
- `bindings.json`
- `bvproject.yaml`
- `pyproject.toml`

Excludes directories:

- `.venv/`
- `__pycache__/`
- `.git/`
- `dist/`

The archive is written deterministically (fixed ZIP timestamps and stable ordering).

## Versioning rules

- Initial version after `bv init` is always `0.0.0`.
- `bv build` never mutates version.
- `bv publish` auto-increments version unless `--dry-run` (and the build, if triggered, uses that bumped version).
	- default is PATCH: `0.0.0 → 0.0.1 → 0.0.2`
	- optional flags: `--major`, `--minor`, `--patch` (default)
- Only `bvproject.yaml` is updated; `pyproject.toml` is not used for name/version.

## Generated main.py template

The `bv init` template is intentionally minimal and compatible with `bv run`:

```python
from __future__ import annotations

from typing import Any

def main(input: dict[str, Any] | None = None) -> dict[str, Any]:
		data = input or {}
		name = str(data.get("name", "World"))
		return {"result": f"Hello {name}"}
```
