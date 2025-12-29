# BV SDK CLI

A Typer-based command-line interface (Python 3.11+) for developing, building, and publishing deterministic Python automations for the Bot Velocity RPA & Agentic Platform.

## Table of Contents

- [Overview](#overview)
- [Installation](#installation)
- [Quick Start](#quick-start)
- [Project Structure](#project-structure)
- [Configuration Files](#configuration-files)
- [CLI Commands](#cli-commands)
  - [Project Management](#project-management)
  - [Entrypoint Management](#entrypoint-management)
  - [Validation](#validation)
  - [Building Packages](#building-packages)
  - [Publishing Packages](#publishing-packages)
  - [Running Automations](#running-automations)
  - [Authentication](#authentication)
  - [Assets Management](#assets-management)
  - [Queue Management](#queue-management)
- [Developer-Mode Orchestrator Integration](#developer-mode-orchestrator-integration)
- [Runtime Access](#runtime-access)
- [Package Contract](#package-contract)
- [Versioning](#versioning)
- [Examples](#examples)
- [Troubleshooting](#troubleshooting)

## Overview

The BV SDK CLI is a local-first, deterministic tool for creating Python automations that can be executed on the Bot Velocity platform. Key features:

- **Local-first**: All operations run locally without requiring a connection to Orchestrator (except for developer-mode features)
- **Deterministic**: Build and publish operations produce consistent, reproducible packages
- **Developer-mode**: Optional integration with Orchestrator for local development and testing
- **Project-based**: Uses `bvproject.yaml` as the single source of truth for project configuration
- **SemVer versioning**: Automatic version management with semantic versioning

### Key Properties

- Local-first and deterministic for build/publish/run behavior
- Optional developer-mode Orchestrator integration (interactive user auth) for local development
- The automation contract is `bvproject.yaml`
- `pyproject.toml` is used only for Python dependency management
- Project root is treated as the Python import root (no `src/` layout is assumed)

## Installation

### Prerequisites

- Python 3.11 or higher
- pip (Python package manager)

### Install the CLI

Install the CLI in editable mode for development:

```bash
pip install -e .
```

This installs the `bv` command globally, making it available from any directory.

## Quick Start

### 1. Initialize a New Project

Navigate to an empty directory and initialize a new project:

```bash
bv init [--name <project-name>] [--python <python-exe>]
```

**Options:**
- `--name <project-name>`: Specify a project name (defaults to current directory name)
- `--python <python-exe>`: Specify Python interpreter for the virtual environment (defaults to current Python)

**Behavior:**
- Fails if `bvproject.yaml` already exists
- Creates `.venv/` (project-scoped virtual environment) and `dist/` directory
- Generates initial files:
  - `main.py` - Sample entrypoint function
  - `entry-points.json` - Entrypoint definitions
  - `bindings.json` - Reserved for future extensibility
  - `bvproject.yaml` - Project configuration
  - `pyproject.toml` - Python dependencies
- Initial version is always `0.0.0`
- Project name resolution:
  - If `--name` provided: uses that name
  - Otherwise: uses current directory name (`Path.cwd().name`)

**Example:**
```bash
mkdir my-automation
cd my-automation
bv init --name my-automation
```

### 2. Validate Project Configuration

Validate your project configuration and entrypoints:

```bash
bv validate
```

This checks:
- `bvproject.yaml` exists and is valid
- `version` is valid SemVer
- At least one entrypoint exists
- Exactly one entrypoint is marked `default`
- Each entrypoint's `command` is importable as `module:function` from the project root

### 3. Run Locally

Execute your automation locally (in-process):

```bash
bv run [--entry <name>] [--input <json-file>]
```

**Options:**
- `--entry <name>`: Entrypoint name to run (defaults to project default)
- `--input <json-file>`: Path to JSON file containing input data

**Rules:**
- Uses project root as import root (temporarily inserts it into `sys.path`)
- Does not switch virtual environments
- Does not spawn subprocesses
- Does not perform network calls unless your automation imports and uses `bv.runtime` (developer-mode Orchestrator access)

**Input Handling:**
- If `--input` is omitted: calls the function with `{}` (or no args, depending on signature)
- If `--input` is provided: parses JSON into a dict and passes that as the single argument
- The input JSON must be an object (mapping). Empty input is allowed

**Output Handling:**
- Prints returned value to stdout as JSON when possible, otherwise prints `repr(result)`

**Example:**
```bash
# Run with default entrypoint and no input
bv run

# Run with specific entrypoint and input file
bv run --entry main --input input.json
```

### 4. Build a Package

Build a deterministic `.bvpackage` from your project:

```bash
bv build [--output <path>] [--include <path>...] [--dry-run]
```

**Options:**
- `--output <path>`: Destination `.bvpackage` path (default: `dist/<name>-<version>.bvpackage`)
- `--include <path>...`: Additional project-relative paths to include (files or folders)
- `--dry-run`: Do not write a package, just compute the target path

**Notes:**
- `bv build` MUST NOT change the version
- Build generates `requirements.lock` from the project's venv as part of packaging
- Package includes all source files, excluding `.venv/`, `__pycache__/`, `.git/`, and `dist/`

**Example:**
```bash
# Build package
bv build

# Build with additional files
bv build --include data/ config.json

# Dry run to see target path
bv build --dry-run
```

### 5. Publish Locally

Publish a package locally (auto-increments version):

```bash
bv publish local [<package>] [--major|--minor|--patch] [--move] [--overwrite] [--dry-run]
```

**Options:**
- `<package>`: Path to an existing `.bvpackage` (if absent, build first)
- `--major`: Increment MAJOR version
- `--minor`: Increment MINOR version
- `--patch`: Increment PATCH version (default)
- `--move`: Move instead of copy the artifact into the publish directory
- `--overwrite`: Allow overwriting an existing artifact in the publish directory
- `--dry-run`: Compute targets without copying/moving

**Publish Behavior:**
- Bumps the version in `bvproject.yaml` (unless `--dry-run`)
- Persists the bumped version first, then builds (if needed) using the bumped version
- Copies (or moves) the artifact into `./published/<name>/<version>/`
- Never overwrites an existing artifact unless `--overwrite` is passed

**Example:**
```bash
# Publish with patch version bump (default)
bv publish local

# Publish with minor version bump
bv publish local --minor

# Publish existing package with move
bv publish local dist/my-automation-0.1.0.bvpackage --move
```

## Project Structure

After initialization, your project will have the following structure:

```
my-automation/
├── .venv/              # Project-scoped virtual environment
├── dist/               # Build output directory
├── published/          # Published packages (created on publish)
├── main.py             # Sample entrypoint (generated)
├── entry-points.json   # Entrypoint definitions (generated)
├── bindings.json       # Reserved for future extensibility (generated)
├── bvproject.yaml      # Project configuration (source of truth)
├── pyproject.toml      # Python dependencies
└── requirements.lock   # Locked dependencies (generated on build)
```

### Key Modules

- `src/bv/cli.py`: Typer commands (`init`, `entry …`, `validate`, `run`, `build`, `publish`)
- `src/bv/project/config.py`: `bvproject.yaml` loader, schema, SemVer validation, SemVer bump
- `src/bv/entrypoints/registry.py`: Entrypoint management + import validation (temporarily adds project root to `sys.path`)
- `src/bv/venv/manager.py`: Project-scoped virtualenv creation and `pip freeze`
- `src/bv/packaging/builder.py`: Deterministic `.bvpackage` creation (manifest, entry-points, requirements.lock)
- `src/bv/packaging/bvpackage_validator.py`: BV Package Contract v1 validator
- `docs/bv-package-contract-v1.md`: BV Package Contract v1 (authoritative)

## Configuration Files

### bvproject.yaml (Source of Truth)

The SDK reads these fields from `bvproject.yaml`:

- `name` (project name) - Required
- `version` (SemVer) - Required
- `entrypoints` (commands and default) - Required
- `venv_dir` (virtual environment directory, typically `.venv`) - Optional, defaults to `.venv`
- `orchestrator.url` (optional) - Orchestrator URL for runtime access

This file is required for validate/build/publish/run.

**Minimal Example:**
```yaml
name: demo-automation
version: 0.0.0

entrypoints:
  - name: main
    command: main:main
    default: true

venv_dir: .venv
```

**With Orchestrator URL:**
```yaml
name: demo-automation
version: 0.0.0

entrypoints:
  - name: main
    command: main:main
    default: true

venv_dir: .venv

orchestrator:
  url: http://127.0.0.1:8000
```

### pyproject.toml (Dependencies Only)

`pyproject.toml` is generated/used only for dependency management. It MUST NOT contain `name` or `version`.

**Generated Minimal Structure:**
```toml
[project]
requires-python = ">=3.11"
dependencies = []
```

Add your dependencies here:
```toml
[project]
requires-python = ">=3.11"
dependencies = [
    "requests>=2.32",
    "pandas>=2.0",
]
```

### bindings.json (Reserved / No Runtime Behavior)

`bindings.json` is generated for future extensibility.

- It is NOT validated
- It is NOT required for validate/build/run
- It may be empty

**Example:**
```json
{}
```

### entry-points.json (Generated)

This file is automatically generated and should not be manually edited. It contains entrypoint definitions in a format compatible with the Runner.

## CLI Commands

### Project Management

#### `bv init`

Initialize a new project in the current directory.

```bash
bv init [--name <project-name>] [--python <python-exe>]
```

**Examples:**
```bash
# Use current directory name
bv init

# Specify project name
bv init --name my-automation

# Use specific Python interpreter
bv init --python python3.11
```

### Entrypoint Management

#### `bv entry add`

Add a new entrypoint to the project.

```bash
bv entry add <NAME> --command module:function [--workdir PATH] [--set-default]
```

**Options:**
- `<NAME>`: Entrypoint name (required)
- `--command module:function`: Command in `module:function` format (required)
- `--workdir PATH`: Working directory (relative to project root, optional)
- `--set-default`: Mark this entrypoint as default (optional)

**Examples:**
```bash
# Add a new entrypoint
bv entry add process --command processor:run

# Add entrypoint with working directory
bv entry add worker --command worker:main --workdir workers/

# Add and set as default
bv entry add main --command main:main --set-default
```

#### `bv entry list`

List all entrypoints in the project.

```bash
bv entry list
```

**Output:**
```
main
process
worker
```

#### `bv entry set-default`

Set the default entrypoint.

```bash
bv entry set-default <NAME>
```

**Example:**
```bash
bv entry set-default process
```

### Validation

#### `bv validate`

Validate project configuration and entrypoints.

```bash
bv validate [--config <path>] [--project-root <path>]
```

**Options:**
- `--config <path>`: Path to `bvproject.yaml` (default: `bvproject.yaml`)
- `--project-root <path>`: Project root for resolving paths (default: `.`)

**Checks:**
- `bvproject.yaml` exists and is valid
- `version` is valid SemVer
- At least one entrypoint exists
- Exactly one entrypoint is marked `default`
- Each entrypoint's `command` is importable as `module:function` from the project root
- Workdir paths exist (if specified)

**Example:**
```bash
bv validate
```

**Output:**
```
Project configuration is valid.
```

### Building Packages

#### `bv build`

Build a deterministic `.bvpackage` from the project.

```bash
bv build [--output <path>] [--include <path>...] [--dry-run]
```

**Options:**
- `--output <path>`: Destination `.bvpackage` path (default: `dist/<name>-<version>.bvpackage`)
- `--include <path>...`: Additional project-relative paths to include (files or folders)
- `--dry-run`: Do not write a package, just compute the target path

**What Gets Packaged:**
- `main.py` (and all Python modules referenced by entrypoints)
- `entry-points.json`
- `bindings.json`
- `bvproject.yaml`
- `pyproject.toml`
- `requirements.lock` (generated during build)
- Additional files specified with `--include`

**Excluded Directories:**
- `.venv/`
- `__pycache__/`
- `.git/`
- `dist/`

The archive is written deterministically (fixed ZIP timestamps and stable ordering).

**Examples:**
```bash
# Standard build
bv build

# Build to specific location
bv build --output packages/my-automation.bvpackage

# Include additional files
bv build --include data/ config.json templates/

# Dry run
bv build --dry-run
```

### Publishing Packages

#### `bv publish local`

Publish a package locally (auto-increments version).

```bash
bv publish local [<package>] [--major|--minor|--patch] [--move] [--overwrite] [--dry-run]
```

**Options:**
- `<package>`: Path to an existing `.bvpackage` (if absent, build first)
- `--major`: Increment MAJOR version
- `--minor`: Increment MINOR version
- `--patch`: Increment PATCH version (default)
- `--move`: Move instead of copy the artifact
- `--overwrite`: Allow overwriting an existing artifact
- `--dry-run`: Compute targets without copying/moving

**Examples:**
```bash
# Publish with patch bump (0.0.0 → 0.0.1)
bv publish local

# Publish with minor bump (0.0.1 → 0.1.0)
bv publish local --minor

# Publish with major bump (0.1.0 → 1.0.0)
bv publish local --major

# Publish existing package
bv publish local dist/my-automation-0.1.0.bvpackage

# Move instead of copy
bv publish local --move
```

#### `bv publish orchestrator`

Publish a package to Orchestrator (developer-mode, safe preflight).

```bash
bv publish orchestrator [--include <path>...]
```

**Options:**
- `--include <path>...`: Additional project-relative paths to include during build

**Prerequisites:**
- You must be authenticated first: `bv auth login ...`

**Process:**
1. Reads `bvproject.yaml` (name + SemVer version)
2. Builds a deterministic `.bvpackage` using the existing `bv build` logic
3. Calls `POST /api/packages/preflight` and stops if rejected
4. Uploads the package via `POST /api/packages/upload` (multipart/form-data)
5. Prints: `Published <name>@<version> to <orchestrator-url>`

**Notes:**
- Orchestrator is the final authority for publish validation
- The SDK does not retry uploads automatically
- Version is NOT bumped (use `bv publish local` first if you want to bump)

**Example:**
```bash
# Authenticate first
bv auth login --api-url http://127.0.0.1:8000 --ui-url http://localhost:5173

# Publish to orchestrator
bv publish orchestrator
```

### Running Automations

#### `bv run`

Run a configured entrypoint locally (in-process).

```bash
bv run [--entry <name>] [--input <json-file>]
```

**Options:**
- `--entry <name>`: Entrypoint name (defaults to project default)
- `--input <json-file>`: Path to a JSON file to pass as input

**Execution Model:**
- Uses project root as import root (temporarily inserts it into `sys.path`)
- Does not switch virtual environments
- Does not spawn subprocesses
- Does not perform network calls unless your automation imports and uses `bv.runtime` (developer-mode Orchestrator access)

**Input Handling:**
- If `--input` is omitted: calls the function with `{}` (or no args, depending on signature)
- If `--input` is provided: parses JSON into a dict and passes that as the single argument
- The input JSON must be an object (mapping). Empty input is allowed

**Output Handling:**
- Prints returned value to stdout as JSON when possible, otherwise prints `repr(result)`

**Function Signature Support:**
The CLI intelligently handles different function signatures:
- `def main()` - Called with no arguments
- `def main(input: dict)` - Called with input dict (or `{}` if no input provided)
- `def main(input: dict | None = None)` - Called with input dict or `None`

**Examples:**
```bash
# Run default entrypoint with no input
bv run

# Run specific entrypoint
bv run --entry process

# Run with input file
bv run --input input.json

# Run specific entrypoint with input
bv run --entry worker --input data.json
```

**Input File Example (`input.json`):**
```json
{
  "name": "John",
  "age": 30,
  "tasks": ["task1", "task2"]
}
```

### Authentication

#### `bv auth login`

Authenticate this machine for SDK developer mode.

```bash
bv auth login --api-url <url> --ui-url <url>
```

**Options:**
- `--api-url <url>`: Orchestrator API base URL (e.g., `http://127.0.0.1:8000`)
- `--ui-url <url>`: Orchestrator UI base URL (e.g., `http://localhost:5173`)

**Flow:**
1. SDK calls `POST {api-url}/api/sdk/auth/start` (includes machine name)
2. SDK opens `{ui-url}/#/sdk-auth?session_id=...`
3. SDK polls `GET {api-url}/api/sdk/auth/status?session_id=...` every 2 seconds
4. On success, SDK writes `~/.bv/auth.json` and overwrites any existing auth

**Timeout:** 5 minutes

**Diagnostics:**
- The CLI prints the exact URL it opens (never prints tokens)
- While polling, it prints a short message about every ~10 seconds:
  - `Waiting for browser authentication… (open tab if not already)`
- If you are redirected to the dashboard after login, ensure the URL still contains `#/sdk-auth?session_id=...`
- If the auth session expires, the CLI stops and tells you to run `bv auth login` again

**Session Reuse:**
- If the backend reuses an existing auth session for the same machine, the CLI prints `Reusing existing auth session …` and continues normally

**Example:**
```bash
bv auth login --api-url http://127.0.0.1:8000 --ui-url http://localhost:5173
```

#### `bv auth status`

Show current SDK authentication status.

```bash
bv auth status
```

**Output:**
```
Logged in
api_url: http://127.0.0.1:8000
ui_url: http://localhost:5173
expires_at: 2024-01-01T12:00:00Z
username: admin
machine_name: DEV-HOST-01
```

**Note:** Never prints the token

#### `bv auth logout`

Delete local SDK authentication.

```bash
bv auth logout
```

**Output:**
```
Logged out (deleted ~/.bv/auth.json)
```

**Token Storage:**

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

### Assets Management

#### `bv assets list`

List assets from Orchestrator.

```bash
bv assets list [--search TEXT]
```

**Options:**
- `--search TEXT`: Search assets by name

**Prerequisites:**
- Must be authenticated: `bv auth login ...`

**Example:**
```bash
bv assets list
bv assets list --search config
```

**Output:**
```json
[
  {
    "name": "MY_CONFIG",
    "type": "string",
    "value": "production"
  },
  {
    "name": "API_KEY",
    "type": "secret",
    "value": "***"
  }
]
```

**Note:** Secret/credential-like assets are masked in CLI output as `"***"`

#### `bv assets get`

Get an asset by name.

```bash
bv assets get <name>
```

**Prerequisites:**
- Must be authenticated: `bv auth login ...`

**Example:**
```bash
bv assets get MY_CONFIG
```

**Output:**
```json
{
  "name": "MY_CONFIG",
  "type": "string",
  "value": "production"
}
```

### Queue Management

#### `bv queues list`

List queues from Orchestrator.

```bash
bv queues list
```

**Prerequisites:**
- Must be authenticated: `bv auth login ...`

**Example:**
```bash
bv queues list
```

**Output:**
```json
[
  {
    "name": "orders"
  },
  {
    "name": "results"
  }
]
```

#### `bv queues put`

Enqueue a queue item.

```bash
bv queues put <queue-name> --input <json-file>
```

**Options:**
- `<queue-name>`: Queue name (required)
- `--input <json-file>`: Path to JSON payload file (required)

**Prerequisites:**
- Must be authenticated: `bv auth login ...`

**Example:**
```bash
# Create payload.json
echo '{"order_id": 123, "status": "pending"}' > payload.json

# Enqueue
bv queues put orders --input payload.json
```

#### `bv queues get`

Dequeue the next available item from a queue.

```bash
bv queues get <queue-name>
```

**Prerequisites:**
- Must be authenticated: `bv auth login ...`

**Example:**
```bash
bv queues get orders
```

**Output:**
```json
{
  "order_id": 123,
  "status": "pending"
}
```

Returns `null` if the queue is empty.

## Developer-Mode Orchestrator Integration

The SDK supports a **developer-only** authentication mode that lets you call Orchestrator APIs while developing locally.

This is explicitly NOT runner execution, NOT unattended automation, and NOT production auth.

### Strict Boundaries

This SDK auth mode MUST NOT be used to:
- Register robots
- Send machine heartbeats
- Execute jobs
- Call runner APIs
- Use robot/service-account tokens

### Authentication Flow

1. **Login**: Authenticate interactively via the browser
   ```bash
   bv auth login --api-url http://127.0.0.1:8000 --ui-url http://localhost:5173
   ```

2. **Check Status**: Verify authentication
   ```bash
   bv auth status
   ```

3. **Use Assets/Queues**: Access Orchestrator resources
   ```bash
   bv assets list
   bv queues list
   ```

### Runtime Access During `bv run`

During `bv run`, automation code can access assets and queues via:

```python
from bv.runtime import assets, queues

# Get an asset
value = assets.get("MY_CONFIG")

# Queue operations
item = queues.get("orders")
queues.put("results", {"id": 1})
queues.list()
```

These runtime modules are only available when your code is executed via `bv run`. They fail fast if used outside of `bv run` or if you are not authenticated.

## Runtime Access

The `bv.runtime` module provides access to Orchestrator resources during local execution.

### Assets

```python
from bv.runtime import assets

# Get an asset value
config_value = assets.get("MY_CONFIG")
api_key = assets.get("API_KEY")
```

**Behavior:**
- Only available when running via `bv run`
- Requires authentication (`bv auth login`)
- Raises `RuntimeError` if not running via `bv run`
- Raises `AuthError` if not authenticated

### Queues

```python
from bv.runtime import queues

# List queues
queue_names = queues.list()

# Get next item from queue
item = queues.get("orders")

# Put item into queue
queues.put("results", {"id": 1, "status": "completed"})
```

**Behavior:**
- Only available when running via `bv run`
- Requires authentication (`bv auth login`)
- Raises `RuntimeError` if not running via `bv run`
- Raises `AuthError` if not authenticated

### Guard Mechanism

The runtime modules use a guard mechanism to ensure they're only used in the correct context:

```python
# bv/runtime/_guard.py
def require_bv_run() -> None:
    if os.environ.get("BV_SDK_RUN") != "1":
        raise RuntimeError("bv.runtime is only available when running via bv run")
```

## Package Contract

The BV Package Contract v1 defines the structure and validation rules for `.bvpackage` files.

### Required Files

A `.bvpackage` MUST contain these files (at the archive root):
- `bvproject.yaml`
- `entry-points.json`
- `pyproject.toml`

### Optional Files

A `.bvpackage` MAY include:
- `bindings.json`
- User Python modules/files (e.g., `main.py`, packages, resources)
- Additional derived artifacts (e.g., `requirements.lock`, `manifest.json`)

### Forbidden Content

A `.bvpackage` MUST NOT contain any of the following directories anywhere in the archive:
- `.venv/`
- `__pycache__/`
- `dist/`
- `.git/`

### Validation

The `bv build` command automatically validates packages against the contract. You can also use the validator programmatically:

```python
from bv.packaging.bvpackage_validator import validate_bvpackage_contract_v1

result = validate_bvpackage_contract_v1("dist/my-automation-0.1.0.bvpackage")
print(f"Package: {result.name}@{result.version}")
```

For detailed contract documentation, see `docs/bv-package-contract-v1.md`.

## Versioning

### SemVer Format

Versions must follow Semantic Versioning (SemVer) format:
- `MAJOR.MINOR.PATCH` (e.g., `1.2.3`)
- Optional pre-release: `1.2.3-alpha.1`
- Optional build metadata: `1.2.3+20240101`

### Version Rules

- Initial version after `bv init` is always `0.0.0`
- `bv build` never mutates version
- `bv publish local` auto-increments version unless `--dry-run` (and the build, if triggered, uses that bumped version)
  - Default is PATCH: `0.0.0 → 0.0.1 → 0.0.2`
  - Optional flags: `--major`, `--minor`, `--patch` (default)
- Only `bvproject.yaml` is updated; `pyproject.toml` is not used for name/version

### Version Bumping Examples

```bash
# Current version: 0.0.0
bv publish local          # → 0.0.1 (patch)
bv publish local --patch  # → 0.0.2 (patch)
bv publish local --minor  # → 0.1.0 (minor)
bv publish local --major  # → 1.0.0 (major)
```

## Examples

### Example 1: Simple Automation

**1. Initialize Project:**
```bash
mkdir hello-world
cd hello-world
bv init --name hello-world
```

**2. Edit `main.py`:**
```python
from __future__ import annotations
from typing import Any

def main(input: dict[str, Any] | None = None) -> dict[str, Any]:
    data = input or {}
    name = str(data.get("name", "World"))
    return {"message": f"Hello, {name}!"}
```

**3. Run Locally:**
```bash
bv run
# Output: {"message": "Hello, World!"}

echo '{"name": "Alice"}' > input.json
bv run --input input.json
# Output: {"message": "Hello, Alice!"}
```

**4. Build and Publish:**
```bash
bv build
bv publish local
```

### Example 2: Using Runtime Assets

**1. Authenticate:**
```bash
bv auth login --api-url http://127.0.0.1:8000 --ui-url http://localhost:5173
```

**2. Create Automation with Asset Access:**
```python
from __future__ import annotations
from typing import Any
from bv.runtime import assets

def main(input: dict[str, Any] | None = None) -> dict[str, Any]:
    # Get configuration from Orchestrator
    api_url = assets.get("API_URL")
    api_key = assets.get("API_KEY")
    
    # Use the configuration
    return {
        "api_url": api_url,
        "has_key": bool(api_key)
    }
```

**3. Run:**
```bash
bv run
```

### Example 3: Queue Processing

**1. Create Queue Processor:**
```python
from __future__ import annotations
from typing import Any
from bv.runtime import queues

def main(input: dict[str, Any] | None = None) -> dict[str, Any]:
    # Get next item from queue
    item = queues.get("orders")
    
    if item is None:
        return {"status": "no_items"}
    
    # Process item
    order_id = item.get("order_id")
    result = {"processed": order_id}
    
    # Put result back
    queues.put("results", result)
    
    return result
```

**2. Run:**
```bash
bv run
```

### Example 4: Multiple Entrypoints

**1. Add Entrypoints:**
```bash
bv entry add process --command processor:run
bv entry add worker --command worker:main
```

**2. Create Modules:**
```python
# processor.py
def run(input: dict | None = None) -> dict:
    return {"status": "processed"}

# worker.py
def main(input: dict | None = None) -> dict:
    return {"status": "working"}
```

**3. Run Specific Entrypoint:**
```bash
bv run --entry process
bv run --entry worker
```

## Troubleshooting

### Common Issues

#### 1. "Config not found at bvproject.yaml"

**Problem:** The CLI cannot find `bvproject.yaml`.

**Solution:**
- Ensure you're in the project root directory
- Run `bv init` if the project hasn't been initialized
- Use `--config <path>` to specify a custom path

#### 2. "Cannot import module 'main'"

**Problem:** Entrypoint command references a module that cannot be imported.

**Solution:**
- Ensure the module file exists in the project root
- Check that the module name matches the file name (without `.py`)
- Verify the function name matches the entrypoint command
- Run `bv validate` to check all entrypoints

#### 3. "Token expired. Run bv auth login"

**Problem:** Authentication token has expired.

**Solution:**
```bash
bv auth logout
bv auth login --api-url <url> --ui-url <url>
```

#### 4. "bv.runtime is only available when running via bv run"

**Problem:** Trying to use `bv.runtime` outside of `bv run`.

**Solution:**
- Only import and use `bv.runtime` when your code is executed via `bv run`
- Do not use `bv.runtime` in scripts that run directly with Python

#### 5. "Package name mismatch" or "Package version mismatch"

**Problem:** Package contents don't match `bvproject.yaml`.

**Solution:**
- Rebuild the package: `bv build`
- Ensure `bvproject.yaml` has the correct name and version
- Check that you're publishing the correct package

#### 6. "Published artifact already exists"

**Problem:** Trying to publish a version that already exists.

**Solution:**
- Use `--overwrite` to replace existing artifact
- Or bump the version first: `bv publish local --patch`

#### 7. "Virtual environment not found"

**Problem:** The project's virtual environment is missing.

**Solution:**
- Recreate the venv: `python -m venv .venv`
- Or reinitialize the project: `bv init` (will fail if config exists, so remove it first if needed)

#### 8. "Entrypoint does not accept input"

**Problem:** Function signature doesn't match the input being provided.

**Solution:**
- Update function signature to accept `input: dict | None = None`
- Or remove `--input` if the function doesn't accept arguments
- Check function signature with `inspect.signature()`

### Getting Help

- Run `bv --help` for general help
- Run `bv <command> --help` for command-specific help
- Check `bv validate` output for configuration issues
- Review `docs/bv-package-contract-v1.md` for package contract details

## License

Proprietary

## Support

For issues, questions, or contributions, please contact the Bot Velocity Team.
