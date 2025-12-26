# BV Package Contract v1 (Authoritative)

**Status:** Locked (v1)

This document defines the authoritative contract for a Bot Velocity package artifact: a `.bvpackage`.

## 1) What a `.bvpackage` is

A `.bvpackage` is a deterministic ZIP archive produced by `bv-sdk-cli`.

The Orchestrator and Runner MAY assume:
- The archive is a valid ZIP.
- Required files exist.
- `bvproject.yaml` is the single source of truth for package identity and entrypoints.

## 2) Required files (MUST exist)

A `.bvpackage` MUST contain these files (at the archive root):
- `bvproject.yaml`
- `entry-points.json`
- `pyproject.toml`

## 3) Optional files

A `.bvpackage` MAY include:
- `bindings.json`
- user Python modules/files (for example `main.py`, packages, resources)
- additional derived artifacts (for example `requirements.lock`, `manifest.json`) so long as they do not violate the forbidden rules below

## 4) Forbidden content

A `.bvpackage` MUST NOT contain any of the following directories anywhere in the archive:
- `.venv/`
- `__pycache__/`
- `dist/`
- `.git/`

## 5) `bvproject.yaml` (Authoritative)

`bvproject.yaml` is the single source of truth.

### Schema (v1)

- `name`: string (required)
- `version`: SemVer string (required, immutable)
- `entrypoints`: list (required)
  - `name`: string (unique)
  - `command`: string, format `module:function`
  - `default`: boolean (exactly one entrypoint MUST have `default: true`)

### Rules

- `bvproject.yaml` is the single source of truth.
- `version` MUST NOT be modified by Orchestrator.
- `name + version` uniquely identify a package.

## 6) `entry-points.json`

- Derived artifact.
- MUST match `bvproject.yaml` entrypoints.
- Used by the Runner at execution time.

### Consistency rules (v1)

For every entrypoint declared in `bvproject.yaml`:
- `entry-points.json` MUST contain an entry with the same `name`.
- Exactly one entry MUST be marked default.
- It MUST be possible to derive the `module:function` command from `entry-points.json` and it MUST equal the authoritative `bvproject.yaml` `command`.

Note: the on-disk JSON representation may include either:
- a `command` field directly, OR
- a `filePath` + `function` pair from which `module:function` is derived (for example `main.py` + `main` -> `main:main`).

## 7) Execution contract

- Orchestrator selects:
  - package (`name + version`)
  - entrypoint name
- Runner executes:
  - entrypoint command (`module:function`)
- Orchestrator MUST NOT reference script paths directly.
- `script_path` is invalid for bvpackages.

## 8) Immutability rules

- `name + version` is immutable.
- The same `name + version` MUST NOT be uploaded twice.
- Jobs snapshot:
  - `package_name`
  - `package_version`
  - `entrypoint_name`

## 9) Validation

A validator for Contract v1 MUST:
- detect `.bvpackage`
- open ZIP and validate:
  - required files exist
  - forbidden paths are absent
  - `bvproject.yaml` schema and rules
  - entrypoints correctness (unique names, valid `module:function`, exactly one default)
  - `entry-points.json` consistency with `bvproject.yaml`
- produce clear, actionable errors
