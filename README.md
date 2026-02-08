# Getting Started with Bot Velocity SDK CLI

The Bot Velocity SDK CLI (`bv`) is a developer-facing command-line tool for authoring, testing, and publishing RPA automation packages to the Bot Velocity platform.

It gives RPA developers a complete local-first workflow: initialize projects, run automations against live Orchestrator resources in development mode, and publish immutable `.bvpackage` artifacts to Orchestrator — all from the terminal.

**The CLI is a development and publishing tool.** It does not execute production jobs. Production execution is handled exclusively by the Bot Velocity Runner, which operates under its own identity, tokens, and security boundary. The CLI never participates in production workloads.

### Where the CLI fits in the Bot Velocity platform

| Component | Role |
|-----------|------|
| **SDK CLI** (`bv`) | Author, validate, build, and publish automation packages from a developer workstation. |
| **Orchestrator** | Central control plane — stores packages, manages assets, queues, credentials, folders, and job schedules. |
| **Runner** | Production execution engine — pulls packages from Orchestrator, provisions environments, and runs jobs. |
| **Runtime SDK** (`bv-runtime`) | In-process library used by automation code to interact with assets, queues, and logging at runtime. |

The CLI bridges the gap between writing automation code locally and deploying it to the platform. Developers authenticate once, iterate with live Orchestrator resources in dev mode, and publish when ready.

---

## Installation

### Prerequisites

- **Python 3.10 or later** is required.
- A virtual environment is strongly recommended to isolate dependencies.

### Install the CLI

```bash
python -m venv .venv

# Windows
.venv\Scripts\activate

# macOS / Linux
source .venv/bin/activate

pip install bv-sdk-cli
```

### Verify the installation

```bash
bv --help
```

You should see the top-level help output listing all available commands.

---

## Authentication

The SDK CLI uses browser-based OAuth to authenticate developers against the Orchestrator. No environment variables, API keys, or manual token management are involved.

### How authentication works

1. The developer runs `bv auth login` and provides the canonical Orchestrator URL.
2. The CLI opens a browser window to the Orchestrator's authentication page.
3. The developer signs in through the standard platform login flow.
4. On success, the CLI receives a short-lived JWT and stores it locally.

All subsequent CLI commands that contact the Orchestrator (assets, queues, publish) use this stored JWT automatically.

### Canonical base URL format

Every Orchestrator instance is addressed by a **canonical base URL** that includes the tenant slug:

```
https://cloud.botvelocity.com/{tenant}/orchestrator_
```

For example, if your tenant is `acme`:

```
https://cloud.botvelocity.com/acme/orchestrator_
```

This URL is the single source of truth for all API routing. The CLI derives every endpoint from it — no separate API URL or UI URL is required.

> **How routing works:** The Bot Velocity cloud gateway (Cloudflare) routes requests based on the full path. The `/{tenant}/orchestrator_/` prefix identifies the tenant and directs traffic to the correct backend. There is no path rewriting; the path your CLI sends is the path the backend receives. This means the canonical URL must always include the tenant segment and the `/orchestrator_/` suffix.

### Log in

```bash
bv auth login --base-url https://cloud.botvelocity.com/acme/orchestrator_
```

The CLI will print a URL and attempt to open your default browser. If the browser does not open automatically, copy the URL from the terminal and paste it into a browser manually.

Once authentication completes in the browser, the CLI stores credentials at:

```
~/.bv/auth.json
```

This file is created with restrictive permissions (owner read/write only) and contains:

- The canonical base URL
- A short-lived access token (JWT)
- Token expiration timestamp
- Authenticated user identity
- Machine name

### Check authentication status

```bash
bv auth status
```

Displays whether you are logged in, the base URL, username, token expiration, and machine name.

### Log out

```bash
bv auth logout
```

Deletes `~/.bv/auth.json` and removes all stored credentials from the local machine.

---

## Project Initialization

### Create a new project

```bash
bv init --name "InvoiceBot" --type rpa
```

This creates the following files in the current directory:

```
InvoiceBot/
├── bvproject.yaml      # Project configuration (required)
├── main.py             # Default entrypoint module
└── dist/               # Build output directory (created empty)
```

### Command options

| Option | Required | Description |
|--------|----------|-------------|
| `--name` | Yes | Project name used in configuration and package metadata. |
| `--type` | Yes | Must be `rpa`. |
| `--python-version` | No | Python version to record (default: `3.8`). |
| `--keep-main` | No | Preserve an existing `main.py` instead of overwriting it. |

### The `bvproject.yaml` file

This is the project manifest and the single source of truth for project metadata:

```yaml
project:
  name: InvoiceBot
  type: rpa
  version: 0.0.0
  description: A simple BV project
  entrypoints:
    - name: main
      command: main:main
      default: true
  venv_dir: .venv
  python_version: "3.10"
  dependencies:
    - bv-runtime
    - httpx
    - pandas>=2.0
```

| Field | Required | Description |
|-------|----------|-------------|
| `name` | Yes | Unique project identifier. |
| `type` | Yes | Project type. Use `rpa` for classic RPA automations. |
| `version` | Yes | Semantic version in `MAJOR.MINOR.PATCH` format (e.g., `1.0.0`). |
| `description` | No | Human-readable project description. |
| `entrypoints` | Yes | List of callable entrypoints. At least one is required. |
| `venv_dir` | No | Virtual environment directory name (default: `.venv`). |
| `python_version` | No | Target Python version (default: `3.8`). |
| `dependencies` | Yes | List of pip-installable packages. `bv-runtime` is included by default. |

### Entrypoints

Each entrypoint defines a callable function in your project:

```yaml
entrypoints:
  - name: main
    command: main:main
    default: true
  - name: cleanup
    command: cleanup:run_cleanup
    default: false
```

- `name` — A human-readable identifier for the entrypoint.
- `command` — A `module:function` reference. The module is resolved relative to the project root.
- `default` — Exactly one entrypoint must be marked `default: true`. This is the entrypoint used when no `--entry` flag is provided to `bv run`.

---

## Local Development Execution

### What "dev mode" means

Dev mode is the local execution environment provided by `bv run`. It allows developers to run their automation code on their own machine while interacting with live Orchestrator resources (assets, queues, credentials) using their personal authentication context.

Dev mode is **not** production execution. It exists to enable rapid iteration and testing before publishing a package.

### How dev mode differs from production

In dev mode, the CLI:

- Authenticates using the developer's short-lived JWT (not a robot token)
- Initializes a local runtime context so that `bv.runtime.*` APIs function correctly
- Logs output directly to the console (stdout/stderr)
- Does not create execution records in Orchestrator
- Does not enforce runner-level scheduling or retry policies

In production, the Runner:

- Authenticates using long-lived robot tokens provisioned by Orchestrator
- Initializes the runtime context from the job execution metadata
- Captures structured logs and sends them to Orchestrator
- Creates and updates execution records with status, duration, and output
- Enforces scheduling, retry, and failure policies defined in Orchestrator

### Running a project locally

```bash
bv run --entry main
```

| Option | Description |
|--------|-------------|
| `--config` | Path to `bvproject.yaml` (default: current directory). |
| `--entry` | Entrypoint name to run. Uses the default entrypoint if omitted. |
| `--folder` | Folder context for asset and queue access (see next section). |

When `bv run` executes:

1. The project configuration is loaded from `bvproject.yaml`.
2. A runtime context is initialized with the developer's authentication, folder context, and machine identity.
3. The project root is added to `sys.path`.
4. The specified entrypoint function is imported and called.

**Important:** You must install project dependencies in your active virtual environment before running:

```bash
bv build                          # generates requirements.lock
pip install -r requirements.lock  # install pinned dependencies
bv run --entry main               # execute the entrypoint
```

### Logging behavior

In dev mode, all output from `print()` statements and the standard `logging` module is written directly to the console. There is no log capture, no structured log shipping, and no log persistence beyond the terminal session.

In production, the Runner captures and forwards logs to Orchestrator for centralized viewing.

### Runtime context differences

Direct execution via `python main.py` does **not** initialize the runtime context. If your automation code calls `bv.runtime.*` APIs without the runtime context, a `RuntimeError` is raised. Always use `bv run` to execute automations locally.

---

## Folder Context in Dev Mode

Folders in Bot Velocity are logical containers within a tenant that scope access to assets, queues, and credentials. In production, the Runner automatically receives its folder context from the job definition. In dev mode, the developer must provide folder context explicitly.

### How folder context works in dev mode

- The folder is **never inferred automatically**. If folder context is required and not provided, the CLI raises an error.
- Folder access is enforced by the Orchestrator. The authenticated developer must have permission to access the specified folder. The CLI does not bypass folder-level access controls.

### Specifying a folder

Use the `--folder` flag on `bv run`:

```bash
bv run --entry main --folder "Finance"
```

### Folder resolution order

When a runtime API call requires folder context, the following resolution order applies:

| Priority | Source | Description |
|----------|--------|-------------|
| 1 | Runtime API call | A folder override passed directly in the API call (if the API supports it). |
| 2 | `--folder` flag | The folder name provided via `bv run --folder`. |
| 3 | Error | If no folder context is available and the operation requires one, a clear error is raised. |

### Important guarantees

- **Folder overrides never bypass permissions.** Even if a folder name is provided explicitly, the Orchestrator validates that the authenticated user has access to that folder before processing the request.
- **Folder selection affects all scoped resources.** Assets, queues, and credentials are scoped to folders. The folder context determines which resources your automation can access during development.
- **No implicit defaults.** The CLI never assumes a default folder. If you need folder-scoped resources, you must specify one.

---

## Runtime SDK Usage in Dev Mode

The `bv.runtime.*` APIs provide in-process access to Orchestrator resources (assets, queues, credentials) from within your automation code. In dev mode, these APIs are fully functional but operate under a different security and identity model than production.

### How runtime APIs behave in dev mode

- All API calls are authenticated using the developer's JWT from `~/.bv/auth.json`.
- All API calls are routed through the canonical base URL stored during `bv auth login`.
- No robot tokens are used or required. The developer's personal identity is the execution identity.
- The runtime context is initialized by `bv run` before your entrypoint is called. Calling runtime APIs outside of `bv run` raises a `RuntimeError`.

### Asset access

Assets are key-value pairs stored in Orchestrator. In dev mode:

- You can list and read assets that your user has permission to access.
- Secret and credential asset values are masked in CLI output (`bv assets get`), but runtime API calls within your automation code receive the actual values (subject to permissions).
- Asset access is scoped to the folder context provided via `--folder`.

```bash
# List assets via CLI
bv assets list
bv assets list --search "invoice"

# Get a specific asset via CLI
bv assets get DB_CONNECTION_STRING
```

### Queue access

Queues are FIFO data structures in Orchestrator used to pass work items between automations. In dev mode:

- You can list queues, enqueue items, and dequeue items.
- Queue access is scoped to the folder context provided via `--folder`.

```bash
# List queues via CLI
bv queues list

# Enqueue an item
bv queues put "InvoiceQueue" --input payload.json

# Dequeue the next item
bv queues get "InvoiceQueue"
```

### Secret handling

Secrets and credentials stored in Orchestrator are never written to disk by the CLI outside of `~/.bv/auth.json` (which contains only the developer's own access token). Secret values returned by runtime APIs are held in memory only and are not logged or persisted by the CLI.

---

## Publishing Packages

Publishing is the process of packaging your automation code into an immutable `.bvpackage` artifact and uploading it to Orchestrator (or saving it locally for testing).

### Step 1: Validate

```bash
bv validate
```

Runs a comprehensive check against your project:

- `bvproject.yaml` exists and is valid YAML with all required fields.
- `main.py` exists and has valid Python syntax.
- Entrypoint functions are defined and reachable.
- Version is valid semantic versioning format.
- Exactly one entrypoint is marked as default.

### Step 2: Build

```bash
bv build
```

Builds a `.bvpackage` file in the `dist/` directory. The build process:

1. Validates the project configuration.
2. Creates a temporary virtual environment to resolve and lock dependencies.
3. Generates `requirements.lock` with pinned dependency versions.
4. Packages all required files into a ZIP archive.

| Option | Description |
|--------|-------------|
| `--config` | Path to `bvproject.yaml` (default: current directory). |
| `--output` | Custom output path (default: `dist/<name>-<version>.bvpackage`). |
| `--dry-run` | Compute the target path without producing a package. |

**Package contents:**

| File | Description |
|------|-------------|
| `bvproject.yaml` | Project configuration. |
| `main.py` | Automation source code. |
| `requirements.lock` | Pinned dependency versions. |
| `manifest.json` | Package metadata (name, version, entrypoint, Python version). |
| `entry-points.json` | Derived entrypoint metadata for the Runner. |

> **Note:** `bv build` never bumps the project version. It packages whatever version is currently in `bvproject.yaml`.

### Step 3: Publish to Orchestrator

```bash
bv publish orchestrator --patch
```

Publishes the package to Orchestrator. This command:

1. Bumps the version in `bvproject.yaml` (patch by default, or `--minor` / `--major`).
2. Regenerates `requirements.lock`.
3. Builds the `.bvpackage`.
4. Sends a preflight check to Orchestrator to verify the package name and version are available.
5. Uploads the package to Orchestrator.

| Option | Description |
|--------|-------------|
| `--config` | Path to `bvproject.yaml`. |
| `--major` | Bump major version (e.g., `1.0.0` → `2.0.0`). |
| `--minor` | Bump minor version (e.g., `1.0.0` → `1.1.0`). |
| `--patch` | Bump patch version (default, e.g., `1.0.0` → `1.0.1`). |

**Prerequisite:** You must be authenticated via `bv auth login` before publishing.

### Publish locally (for testing)

```bash
bv publish local --output-dir ./releases --minor
```

Performs the same validation, version bump, and build steps, but copies the resulting `.bvpackage` to a local directory instead of uploading to Orchestrator. Useful for offline testing or CI artifact staging.

### Package immutability

Once a package version is published to Orchestrator, it cannot be overwritten or deleted. Each `name@version` combination is unique and permanent. To publish changes, bump the version and publish again.

### What the CLI does not do

The CLI publishes packages — it does not create jobs, assign packages to Runners, or trigger execution. Job scheduling and execution management are performed through the Orchestrator UI or API.

---

## Dev Mode vs Production Comparison

| Aspect | Dev Mode (`bv run`) | Production (Runner) |
|--------|---------------------|---------------------|
| **Auth method** | Developer JWT from `~/.bv/auth.json` | Robot token provisioned by Orchestrator |
| **Folder resolution** | Explicit via `--folder` flag; never inferred | Assigned by Orchestrator job definition |
| **Logging** | Console output (stdout/stderr) | Structured logs shipped to Orchestrator |
| **Execution identity** | Developer's personal user account | Robot identity bound to the Runner |
| **Failure behavior** | Exception printed to console; process exits | Execution marked as failed in Orchestrator; retry policies applied |
| **Permissions** | Developer's folder and resource permissions | Robot's folder and resource permissions |
| **Execution record** | None created | Full execution lifecycle tracked in Orchestrator |
| **Scheduling** | Manual (`bv run`) | Orchestrator-managed schedules and triggers |

---

## Common Errors and Troubleshooting

### Folder context required

```
Error: folder context is required for this operation
```

**What it means:** Your automation code attempted to access a folder-scoped resource (asset, queue, or credential), but no folder context was provided.

**How to fix it:** Add the `--folder` flag to your `bv run` command:

```bash
bv run --entry main --folder "Finance"
```

---

### Not authenticated

```
Error: Not authenticated. Run 'bv auth login'
```

**What it means:** No valid credentials were found in `~/.bv/auth.json`, or the stored token has expired.

**How to fix it:** Authenticate again:

```bash
bv auth login --base-url https://cloud.botvelocity.com/acme/orchestrator_
```

---

### Invalid base URL

```
Error: Invalid platform URL: Canonical URL must include '/{tenant}/orchestrator_/'
```

**What it means:** The URL provided to `--base-url` is missing the tenant segment or the `/orchestrator_/` suffix.

**How to fix it:** Use the full canonical URL format:

```bash
bv auth login --base-url https://cloud.botvelocity.com/acme/orchestrator_
```

Replace `acme` with your actual tenant slug.

---

### Tenant mismatch

```
Error: Permission denied
```

**What it means:** The authenticated user does not have access to the tenant or resource being accessed. This can happen when the base URL points to a tenant that the user is not a member of.

**How to fix it:**

1. Verify the base URL matches your assigned tenant: `bv auth status`
2. Confirm with your platform administrator that your user account has access to the target tenant.
3. Re-authenticate if the tenant has changed: `bv auth logout && bv auth login --base-url <correct-url>`

---

### Permission denied

```
Error: Permission denied: User does not have access to folder 'Finance'
```

**What it means:** The authenticated user does not have the required permissions on the specified folder or resource.

**How to fix it:**

1. Verify you are using the correct folder name: `bv run --folder "Finance"`
2. Contact your platform administrator to request access to the required folder.
3. Check that the folder name matches exactly (folder names are case-sensitive).

---

### Runtime APIs failing outside `bv run`

```
RuntimeError: bv.runtime APIs require initialization via bv run
```

**What it means:** Your code called a `bv.runtime.*` API, but the runtime context was not initialized. This happens when you run `python main.py` directly instead of using `bv run`.

**How to fix it:** Always execute your automation through the CLI:

```bash
bv run --entry main
```

---

### Module not found during `bv run`

```
ModuleNotFoundError: No module named 'httpx'
```

**What it means:** A dependency required by your automation code is not installed in the active Python environment.

**How to fix it:**

```bash
bv build                          # generates requirements.lock
pip install -r requirements.lock  # install dependencies
bv run --entry main
```

---

### Build fails with dependency resolution errors

**What it means:** The `bv build` command could not resolve one or more dependencies listed in `bvproject.yaml`.

**How to fix it:**

1. Verify package names in `bvproject.yaml` match their PyPI names exactly.
2. Check network connectivity to PyPI.
3. If using a private package index, ensure it is configured in your pip settings.

---

## Security and Guarantees

### No environment variables

The SDK CLI does not read platform URLs, tokens, or credentials from environment variables. All configuration originates from `~/.bv/auth.json`, which is set during `bv auth login`. This eliminates an entire class of misconfiguration and credential leakage risks associated with environment variable sprawl.

### Token storage

Developer credentials are stored in `~/.bv/auth.json` with restrictive file permissions (owner read/write only, `0600`). The file contains a short-lived JWT that expires according to the Orchestrator's token policy. No long-lived secrets or API keys are stored on disk.

### Tenant isolation

Every API request includes the tenant identifier as part of the URL path. The Orchestrator enforces tenant isolation at the API layer — a user authenticated against one tenant cannot access resources belonging to another tenant, even if they construct the URL manually.

### Folder access enforcement

Folder-level permissions are enforced server-side by the Orchestrator on every API call. The CLI passes folder context to the Orchestrator, which validates that the authenticated user has the required permissions before returning any data. The CLI never caches or bypasses folder access checks.

### No implicit defaults

The CLI does not assume default values for security-sensitive parameters:

- No default folder is assumed. Folder context must be provided explicitly.
- No default base URL is assumed. The developer must provide the canonical URL during login.
- No fallback authentication is attempted. If the stored token is expired or missing, the CLI fails immediately with a clear error.

---

## What's Next

Once you have published your first package, explore the rest of the Bot Velocity platform:

- **Runtime SDK Documentation** — Learn how to use `bv.runtime.*` APIs for assets, queues, and logging within your automation code.
- **Orchestrator UI Documentation** — Manage packages, create jobs, assign Runners, configure folders, and monitor executions.
- **Runner Installation Guide** — Install and configure Bot Velocity Runners to execute your published automation packages in production.
