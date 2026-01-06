# BV SDK CLI

A Typer-based developer CLI for building, validating, and publishing deterministic automation packages for the Bot Velocity platform. This README is accurate to the current code in this repository and documents every command and file that the CLI touches.

## 1. Overview
- **Purpose**: Provide automation developers and platform integrators with local-first tooling to author Python automations, validate their contracts, build `.bvpackage` artifacts, and optionally publish them to Orchestrator.
- **How it differs from the runner**: The SDK CLI runs on developer machines. It sets `BV_SDK_RUN=1` when invoking code so that `bv.runtime.*` is allowed. The production Runner uses long-lived robot tokens and never relies on the developer auth file or the local SDK commands.
- **Relationship to bv-runtime and bv-orchestrator**: `bv-runtime` is a runtime helper library that projects depend on (added by default in the generated config). The CLI can talk to Orchestrator only in developer mode via the HTTP client in src/bv/orchestrator/client.py.

## 2. Project Philosophy
- **Local-first design**: All core flows (init, validate, build, run) operate purely on local files. Only auth, assets, queues, and publish-orchestrator touch the network.
- **Deterministic builds**: Builds always generate a fresh `requirements.lock` using a throwaway virtual environment (`.bv_tmp_venv`) and package a fixed set of files. Given the same inputs, contents are stable (ZIP timestamps follow the current clock, so byte-for-byte reproducibility is not guaranteed).
- **Separation of dev vs runtime concerns**: SDK auth (human, short-lived) is stored in `~/.bv/auth.json`. Runner-mode auth comes from environment variables (`BV_ORCHESTRATOR_URL`, `BV_ROBOT_TOKEN`, `BV_ROBOT_NAME`) and bypasses the local auth file. The runtime helpers in `bv.runtime` refuse to run unless `BV_SDK_RUN=1` is set by `bv run`.

## 3. Project Initialization (`bv init`)
- **What is created**: `bvproject.yaml` (project config), `main.py` (sample entrypoint), and `dist/` (build output directory). No virtual environment, `requirements.lock`, `entry-points.json`, `bindings.json`, or `pyproject.toml` are created by this command.
- **Generated contents**: `bvproject.yaml` is written with the following structure:
  ```yaml
  project:
    name: <provided name>
    type: rpa|agent
    version: 0.0.0
    description: A simple BV project
    entrypoints:
      - name: main
        command: main:main
        default: true
    venv_dir: .venv
    python_version: "<python-version option>"
    dependencies: ["bv-runtime"]
  ```
  `main.py` contains a placeholder `main()` that prints a greeting.
- **Directory structure after init**:
  ```
  <project-root>/
  ├─ bvproject.yaml
  ├─ main.py
  └─ dist/
  ```
- **Versioning behavior**: Always starts at `0.0.0`. No bump occurs during init.

## 4. Core Configuration Files
- **bvproject.yaml (authoritative contract)**: Source of truth for identity, entrypoints, type, Python version, venv location, and dependency list. Required by validate/build/publish/run. Schema is loaded in src/bv/project/config.py and validated in src/bv/validators/project_validator.py.
- **entry-points.json**: Generated during `bv build` inside the package; mirrors `bvproject.yaml` entrypoints. Not created on disk in the workspace; do not edit manually.
- **bindings.json**: Reserved for future use. The current CLI neither reads nor writes it.
- **pyproject.toml**: Not generated or consumed by the current CLI. The packaging contract document mentions it, but the live build path only relies on `bvproject.yaml`, `main.py`, and `requirements.lock`.

## 5. Command-by-Command Breakdown
All commands live in src/bv/cli.py. Preconditions include having Python 3.11+ available for the CLI itself.

### `bv init`
- **What it does**: Writes `bvproject.yaml` and `main.py` if absent (respects `--keep-main`), creates `dist/`.
- **Preconditions**: Current directory must not already contain `bvproject.yaml`. Requires `--name` and `--type (rpa|agent)`.
- **Files read**: None.
- **Files written/modified**: `bvproject.yaml`, `main.py` (unless `--keep-main` with existing file), `dist/` directory.
- **Side effects**: None beyond file writes. Does not create a venv or install dependencies.

### `bv validate`
- **What it does**: Runs structural validation via src/bv/validators/project_validator.py. Checks file presence, YAML schema, entrypoint format/default, Python version format, dependency list type, and parses `main.py` for syntax and default function existence.
- **Preconditions**: `bvproject.yaml` and `main.py` must exist.
- **Files read**: `bvproject.yaml`, `main.py` (parsed as AST).
- **Files written/modified**: None.
- **Side effects**: Exits non-zero on validation failures; prints warnings for missing `project.type`, missing `__main__` guard, or non-SemVer `version`.

### `bv entry add / list / set-default`
- **What it does**: Not implemented in the current CLI. Entrypoint editing must be done by directly editing `bvproject.yaml` or by using `EntrypointRegistry` programmatically (see src/bv/entrypoints/registry.py).
- **Preconditions**: N/A (commands are absent).
- **Files read**: N/A via CLI.
- **Files written/modified**: N/A via CLI.
- **Side effects**: N/A.

### `bv run`
- **What it does**: Loads `bvproject.yaml`, selects an entrypoint (named via `--entry` or the first default), sets `BV_SDK_RUN=1`, temporarily prepends the project root to `sys.path`, and invokes the entrypoint function without arguments. For script-style commands ending in `.py`, executes the script with `runpy`.
- **Preconditions**: `bvproject.yaml` with at least one entrypoint, `main.py` or other referenced module/script present. Dependencies must already be installed in the active interpreter/venv by the user.
- **Files read**: `bvproject.yaml`, the referenced module or script (e.g., `main.py`).
- **Files written/modified**: None.
- **Side effects**: Sets `BV_SDK_RUN=1` in the environment for the invoked process, enabling `bv.runtime.*` access. Does not switch virtual environments or install packages.

### `bv build`
- **What it does**: Validates the project, generates `requirements.lock` using `RequirementsLockGenerator` (temporary `.bv_tmp_venv`), and writes a `.bvpackage` ZIP containing `bvproject.yaml`, `main.py`, `requirements.lock`, `manifest.json`, and `entry-points.json`.
- **Preconditions**: Valid `bvproject.yaml` and `main.py`; network access for pip to resolve dependencies listed in `project.dependencies`.
- **Files read**: `bvproject.yaml`, `main.py`, dependency list inside `bvproject.yaml`.
- **Files written/modified**: `requirements.lock` (overwritten), target package (default `dist/<name>-<version>.bvpackage` or `--output`), temporary `.bv_tmp_venv/` created and removed.
- **Side effects**: No version changes. Uses current clock for ZIP metadata (non-bit-for-bit determinism). Package contents are limited to the files above—other source files are not included by this builder.

### `bv publish local`
- **What it does**: Validates, bumps version in `bvproject.yaml` (default patch unless `--major` or `--minor`), regenerates `requirements.lock`, builds a `.bvpackage`, and copies it to `<publish_dir>/<name>/<version>/` (default `published/`).
- **Preconditions**: Same as `bv build`; write access to `bvproject.yaml` and publish directory.
- **Files read**: `bvproject.yaml`, `main.py`, dependency list.
- **Files written/modified**: `bvproject.yaml` (version bumped even in `--dry-run`), `requirements.lock`, package in `dist/`, published copy at `<publish_dir>/<name>/<version>/<package>`. Existing target is overwritten (unlinked before copy).
- **Side effects**: Version bump persists even if publish later fails or `--dry-run` is used.

### `bv publish orchestrator`
- **What it does**: Bumps version in `bvproject.yaml` (patch/minor/major), regenerates `requirements.lock`, builds a `.bvpackage`, performs a preflight `POST /api/packages/preflight`, then uploads the package with `POST /api/packages/upload` using developer-mode auth.
- **Preconditions**: Valid project files; developer auth present in `~/.bv/auth.json` or runner env vars; network access to Orchestrator; write access to `bvproject.yaml`.
- **Files read**: `bvproject.yaml`, `main.py`, dependency list.
- **Files written/modified**: `bvproject.yaml` (version bumped before preflight), `requirements.lock`, package in `dist/`.
- **Side effects**: Leaves the bumped version on disk even if preflight rejects or upload fails. Requires active auth; errors if token missing/expired. No local publish directory is used.

### `bv auth login`
- **What it does**: Starts an SDK auth session against Orchestrator (`/api/sdk/auth/start`), opens the browser to `#/sdk-auth?session_id=...`, polls `/api/sdk/auth/status` until a token is issued, then writes `~/.bv/auth.json` (overridable via `BV_AUTH_DIR`).
- **Preconditions**: `--api-url` and `--ui-url` provided; browser access to the UI URL; network reachability to Orchestrator.
- **Files read**: None.
- **Files written/modified**: `~/.bv/auth.json` (JSON with api_url, ui_url, access_token, expires_at, user, machine_name).
- **Side effects**: Opens a browser; caches auth for subsequent commands; fails fast on HTTP errors or expired sessions.

### `bv auth status`
- **What it does**: Reads auth from env (runner mode) or `~/.bv/auth.json` (developer mode), reports whether the token is expired and prints stored fields.
- **Preconditions**: None; handles missing auth gracefully.
- **Files read**: `~/.bv/auth.json` if it exists.
- **Files written/modified**: None.
- **Side effects**: Exit code 0 even when not logged in; prints details about load errors if present.

### `bv auth logout`
- **What it does**: Deletes `~/.bv/auth.json` if present.
- **Preconditions**: None.
- **Files read**: Checks `~/.bv/auth.json` existence.
- **Files written/modified**: Removes `~/.bv/auth.json`.
- **Side effects**: None.

### `bv assets *`
- **What it does**: Developer-mode read access to Orchestrator assets. `bv assets list` queries `/api/assets` with optional `--search`. `bv assets get <name>` fetches `/api/assets/<name>` or falls back to listing + exact match. Secrets/credentials are masked in output.
- **Preconditions**: Developer auth; network access to Orchestrator.
- **Files read**: Auth context file if in developer mode.
- **Files written/modified**: None.
- **Side effects**: Purely read-only; outputs JSON to stdout.

### `bv queues *`
- **What it does**: Developer-mode queue operations. `bv queues list` calls `/api/queues`. `bv queues put --input <json>` posts to `/api/queue-items` (body must be a JSON object). `bv queues get <queue>` fetches from `/api/queue-items/next` (or `/api/queue-items` fallback) and prints one item or `null`.
- **Preconditions**: Developer auth; network access; for `put`, the input file must contain a JSON object.
- **Files read**: Auth context; input JSON file for `put`.
- **Files written/modified**: None locally. Server-side writes occur for `put`.
- **Side effects**: Server-side queue mutations for `put`; `get` may mark items as dequeued depending on backend semantics.

## 6. Build & Publish Lifecycle
- **Version bumps**: `bv build` never bumps. `bv publish local` and `bv publish orchestrator` bump `bvproject.yaml` immediately before building; the new version remains even if later steps fail or `--dry-run` is used.
- **Build vs publish**: Build creates a `.bvpackage` under `dist/`. Local publish copies that artifact to a versioned `published/` tree. Orchestrator publish uploads after a server-side preflight check and does not keep a published copy locally beyond `dist/`.
- **Deterministic packaging guarantees**: Inputs are validated; dependencies are locked via `requirements.lock` generated from a fresh temp venv; package contents are fixed to `bvproject.yaml`, `main.py`, `requirements.lock`, `manifest.json`, `entry-points.json`. ZIP metadata uses current timestamps, so byte-for-byte reproducibility is not promised.

## 7. Developer Mode vs Runner Mode
- **SDK auth (developer mode)**: Short-lived user token stored in `~/.bv/auth.json`, created by `bv auth login`, used by assets/queues/publish-orchestrator. Must never be embedded in production jobs or runners.
- **Runner mode**: Long-lived robot tokens supplied via `BV_ORCHESTRATOR_URL` and `BV_ROBOT_TOKEN` (and optional `BV_ROBOT_NAME`). `bv.auth.context.load_auth_context` prefers these environment variables and marks the user as `robot:<name>`.
- **Runtime access boundaries**: `bv.runtime.assets` and `bv.runtime.queues` call `require_bv_run` and will raise if `BV_SDK_RUN` is not set to `1`. Only `bv run` sets this flag; using these modules from other entrypoints or environments will fail.

## 8. Common Mistakes & Gotchas
- **Entrypoint import errors**: `bv run` prepends the project root only; ensure `command` is `module:function` and the module is importable from the project root. Validator checks only the default entrypoint’s function in `main.py`.
- **Version mismatches**: `bv publish local` and `bv publish orchestrator` bump `bvproject.yaml` before any network or copy step and do not roll back. Even `--dry-run` bumps the file.
- **Package contents**: The current builder includes only `bvproject.yaml`, `main.py`, `requirements.lock`, `manifest.json`, and `entry-points.json`. Additional source files are not packaged; add logic to `main.py` to import what you need or extend the builder.
- **Runtime misuse**: `bv.runtime.*` helpers throw unless `BV_SDK_RUN=1`. The flag is only set by `bv run`; direct script execution without the CLI will fail.
- **Dependency locking**: `requirements.lock` is regenerated on every build/publish using a temp venv and the `project.dependencies` list; if dependencies are missing or private indexes are required, pip resolution will fail. There is no support for reading dependencies from `pyproject.toml` in this CLI version.

## References
- Package contract: docs/bv-package-contract-v1.md
- CLI implementation: src/bv/cli.py
- Validators and builders: src/bv/validators/project_validator.py, src/bv/services/commands.py, src/bv/tools/lock_generator.py, src/bv/packaging/builder.py
- Package validator: src/bv/packaging/bvpackage_validator.py
- Contract document: docs/bv-package-contract-v1.md
