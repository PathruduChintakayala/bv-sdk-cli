# bv-sdk-cli

Typer-based CLI (Python 3.11+) for local-only, deterministic Python automations.

Key properties:

- No network calls.
- No orchestrator integration.
- The automation contract is `bvproject.yaml`.
- `pyproject.toml` is used only for Python dependency management.
- Project root is treated as the Python import root (no `src/` layout is assumed).

## Project layout (key modules)

- `src/bv/cli.py`: Typer commands (`init`, `entry …`, `validate`, `run`, `build`, `publish`)
- `src/bv/project/config.py`: `bvproject.yaml` loader, schema, SemVer validation, SemVer bump
- `src/bv/entrypoints/registry.py`: entrypoint management + import validation (temporarily adds project root to `sys.path`)
- `src/bv/venv/manager.py`: project-scoped virtualenv creation and `pip freeze`
- `src/bv/packaging/builder.py`: deterministic `.bvpackage` creation (manifest, entry-points, requirements.lock)

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
- Does not perform any network calls.

Input handling:

- If `--input` is omitted: calls the function with `{}` (or no args, depending on signature).
- If `--input` is provided: parses JSON into a dict and passes that as the single argument.
- The input JSON must be an object (mapping). Empty input is allowed.

Output handling:

- Prints returned value to stdout as JSON when possible, otherwise prints `repr(result)`.

5) Build a deterministic package:

- `bv build`
- `bv build --dry-run`

Notes:

- `bv build` MUST NOT change the version.
- Build generates `requirements.lock` from the project’s venv as part of packaging.

6) Publish locally (auto-increments version):

- `bv publish` (defaults to PATCH bump)
- `bv publish --major`
- `bv publish --minor`
- `bv publish --patch`

Publish behavior:

- Bumps the version in `bvproject.yaml` (unless `--dry-run`).
- Persists the bumped version first, then builds (if needed) using the bumped version.
- Copies (or moves) the artifact into `./published/<name>/<version>/`.
- Never overwrites an existing artifact unless `--overwrite` is passed.

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
