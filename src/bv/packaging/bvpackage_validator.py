from __future__ import annotations

import json
import re
import zipfile
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any, Iterable

import yaml


class BVPackageContractError(ValueError):
    def __init__(self, errors: list[str]):
        super().__init__("BV Package Contract v1 validation failed")
        self.errors = errors

    def __str__(self) -> str:
        lines = ["BV Package Contract v1 validation failed:"]
        lines.extend(f"- {e}" for e in self.errors)
        return "\n".join(lines)


_SEMVER_RE = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$"
)


@dataclass(frozen=True)
class BVPackageEntrypoint:
    name: str
    command: str
    default: bool


@dataclass(frozen=True)
class BVPackageContractV1Result:
    name: str
    version: str
    entrypoints: tuple[BVPackageEntrypoint, ...]
    warnings: tuple[str, ...] = ()

    @property
    def identity(self) -> tuple[str, str]:
        return (self.name, self.version)

    @property
    def default_entrypoint_name(self) -> str:
        defaults = [e.name for e in self.entrypoints if e.default]
        return defaults[0]


def is_bvpackage_path(path: str) -> bool:
    return path.lower().endswith(".bvpackage")


def validate_bvpackage_contract_v1(path: str) -> BVPackageContractV1Result:
    """Validate a .bvpackage against BV Package Contract v1.

    bvproject.yaml is the SINGLE authoritative source for entrypoints.
    entry-points.json is a derived artifact; its presence is required but
    its content is validated only as a lightweight consistency check
    (non-fatal warnings, not errors).

    Raises:
        BVPackageContractError: if any contract violations are found.
    """

    errors: list[str] = []
    warnings: list[str] = []

    if not is_bvpackage_path(path):
        raise BVPackageContractError([
            f"Not a .bvpackage: {path!r} (expected a path ending in .bvpackage)"
        ])

    try:
        with zipfile.ZipFile(path) as zf:
            members = [n for n in zf.namelist() if not n.endswith("/")]
            _validate_forbidden_paths(members, errors)

            required = ("bvproject.yaml", "entry-points.json")
            prefix = _detect_single_root_prefix(members, required, errors)
            if errors:
                raise BVPackageContractError(errors)

            bvproject_raw = zf.read(prefix + "bvproject.yaml").decode("utf-8")
            entry_points_raw = zf.read(prefix + "entry-points.json").decode("utf-8")

    except zipfile.BadZipFile:
        raise BVPackageContractError([f"Invalid ZIP archive: {path!r}"])
    except FileNotFoundError:
        raise BVPackageContractError([f"File not found: {path!r}"])

    bvproject = _parse_bvproject_yaml(bvproject_raw, errors)
    entrypoints = _parse_and_validate_bvproject_entrypoints(bvproject, errors)

    # entry-points.json consistency check is non-fatal (warnings only).
    # bvproject.yaml is authoritative; entry-points.json is derived.
    _check_entry_points_json_consistency(entry_points_raw, entrypoints, warnings)

    if errors:
        raise BVPackageContractError(errors)

    name = str(bvproject["name"]).strip()
    version = str(bvproject["version"]).strip()
    return BVPackageContractV1Result(
        name=name,
        version=version,
        entrypoints=tuple(entrypoints),
        warnings=tuple(warnings),
    )


def reject_reupload(identity: tuple[str, str], already_uploaded: set[tuple[str, str]]) -> None:
    """Contract helper: reject uploading the same (name, version) twice."""

    if identity in already_uploaded:
        raise BVPackageContractError([
            f"Re-upload rejected: package {identity[0]!r} version {identity[1]!r} already exists"
        ])


def _validate_forbidden_paths(members: Iterable[str], errors: list[str]) -> None:
    forbidden_segments = {".venv", "__pycache__", "dist", ".git"}

    for name in members:
        p = PurePosixPath(name)
        if p.is_absolute() or str(p).startswith(".."):
            errors.append(f"Forbidden path entry: {name!r} (must be relative and not escape root)")
            continue

        if any(seg in forbidden_segments for seg in p.parts):
            errors.append(f"Forbidden content: {name!r} (contains one of {sorted(forbidden_segments)!r})")


def _detect_single_root_prefix(
    members: list[str],
    required_files: tuple[str, ...],
    errors: list[str],
) -> str:
    member_set = set(members)

    prefixes: set[str] = {""}
    for m in members:
        p = PurePosixPath(m)
        if len(p.parts) >= 2:
            prefixes.add(p.parts[0] + "/")

    candidates = [
        prefix
        for prefix in sorted(prefixes, key=lambda s: (len(s), s))
        if all((prefix + req) in member_set for req in required_files)
    ]

    if not candidates:
        missing = [req for req in required_files if req not in member_set]
        if missing:
            errors.append(
                "Missing required files at archive root: "
                + ", ".join(missing)
                + " (required: bvproject.yaml, entry-points.json)"
            )
        else:
            errors.append(
                "Missing required files in a single package root (files exist but not under one common root)"
            )
        return ""

    if len(candidates) > 1:
        errors.append(
            "Ambiguous package root: required files found under multiple prefixes: "
            + ", ".join(repr(c) for c in candidates)
        )
        return ""

    return candidates[0]


def _parse_bvproject_yaml(raw: str, errors: list[str]) -> dict[str, Any]:
    try:
        data = yaml.safe_load(raw)
    except Exception as e:  # pragma: no cover
        errors.append(f"bvproject.yaml is not valid YAML: {e}")
        return {}

    if not isinstance(data, dict):
        errors.append("bvproject.yaml must parse to a mapping/object")
        return {}

    project = data.get("project")
    if not isinstance(project, dict):
        errors.append("bvproject.yaml must contain 'project' mapping")
        return {}
    data = project

    name = data.get("name")
    version = data.get("version")
    if not isinstance(name, str) or not name.strip():
        errors.append("bvproject.yaml: 'name' is required and must be a non-empty string")

    version_str = str(version).strip() if version is not None else ""
    if not version_str:
        errors.append("bvproject.yaml: 'version' is required and must be a SemVer string")
    elif not _SEMVER_RE.match(version_str):
        errors.append(f"bvproject.yaml: 'version' must be SemVer (got {version_str!r})")

    if "entrypoints" not in data:
        errors.append("bvproject.yaml: 'entrypoints' is required")

    return data


def _parse_and_validate_bvproject_entrypoints(
    bvproject: dict[str, Any],
    errors: list[str],
) -> list[BVPackageEntrypoint]:
    eps = bvproject.get("entrypoints")

    if not isinstance(eps, list) or not eps:
        errors.append("bvproject.yaml: 'entrypoints' must be a non-empty list")
        return []

    parsed: list[BVPackageEntrypoint] = []
    seen_names: set[str] = set()
    default_count = 0

    for i, ep in enumerate(eps):
        if not isinstance(ep, dict):
            errors.append(f"bvproject.yaml: entrypoints[{i}] must be an object")
            continue

        name = ep.get("name")
        command = ep.get("command")
        default = ep.get("default")

        if not isinstance(name, str) or not name.strip():
            errors.append(f"bvproject.yaml: entrypoints[{i}].name must be a non-empty string")
            continue

        if name in seen_names:
            errors.append(f"bvproject.yaml: entrypoint name {name!r} is duplicated")
            continue
        seen_names.add(name)

        if not isinstance(command, str) or not command.strip():
            errors.append(f"bvproject.yaml: entrypoints[{i}].command must be a non-empty string")
            continue

        if not _is_module_function(command):
            errors.append(
                f"bvproject.yaml: entrypoints[{i}].command must be 'module:function' (got {command!r})"
            )
            continue

        if not isinstance(default, bool):
            errors.append(f"bvproject.yaml: entrypoints[{i}].default must be a boolean")
            continue

        if default:
            default_count += 1

        parsed.append(BVPackageEntrypoint(name=name, command=command, default=default))

    if default_count != 1:
        errors.append(
            f"bvproject.yaml: exactly one entrypoint must have default: true (found {default_count})"
        )

    return parsed


def _check_entry_points_json_consistency(
    raw: str,
    bvproject_entrypoints: list[BVPackageEntrypoint],
    warnings: list[str],
) -> None:
    """Lightweight, non-fatal consistency check for entry-points.json.

    bvproject.yaml is the authoritative source.  entry-points.json is a
    derived artifact generated by ``derive_entry_points_json()``.  This
    function only emits *warnings* — never errors — because the Runner
    consumes entry-points.json directly and any mismatch indicates a build
    tooling problem, not an invalid package.

    Canonical schema expected::

        {"entrypoints": [{"name": "...", "module": "...", "function": "..."}]}
    """
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        warnings.append(f"entry-points.json is not valid JSON: {e}")
        return

    # Accept both bare list and {"entrypoints": [...]} wrapper
    if isinstance(data, dict):
        eps_list = data.get("entrypoints")
        if not isinstance(eps_list, list):
            warnings.append(
                "entry-points.json: expected 'entrypoints' array in object"
            )
            return
    elif isinstance(data, list):
        eps_list = data
    else:
        warnings.append("entry-points.json: must be a JSON object or array")
        return

    # Collect names from entry-points.json
    json_names: set[str] = set()
    json_by_name: dict[str, dict[str, Any]] = {}
    for ep in eps_list:
        if isinstance(ep, dict):
            name = ep.get("name")
            if isinstance(name, str) and name.strip():
                json_names.add(name.strip())
                json_by_name[name.strip()] = ep

    # Compare name sets
    expected_names = {e.name for e in bvproject_entrypoints}
    missing = sorted(expected_names - json_names)
    extra = sorted(json_names - expected_names)

    if missing:
        warnings.append(
            "entry-points.json drift: missing entrypoints from bvproject.yaml: "
            + ", ".join(missing)
        )
    if extra:
        warnings.append(
            "entry-points.json drift: unexpected entrypoints not in bvproject.yaml: "
            + ", ".join(extra)
        )

    # Per-entrypoint command consistency
    for ep in bvproject_entrypoints:
        jp = json_by_name.get(ep.name)
        if not jp:
            continue

        # Reconstruct command from module:function
        module = jp.get("module", "")
        function = jp.get("function", "")
        if module and function:
            derived = f"{module}:{function}"
            if derived != ep.command:
                warnings.append(
                    f"entry-points.json drift: entrypoint {ep.name!r} command mismatch "
                    f"(bvproject.yaml={ep.command!r}, entry-points.json={derived!r})"
                )


_MODULE_PART_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*$")
_FUNC_PART_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _is_module_function(command: str) -> bool:
    if ":" not in command:
        return False

    module, func = command.split(":", 1)
    module = module.strip()
    func = func.strip()

    if not module or not func:
        return False

    if "/" in module or "\\" in module:
        return False

    return bool(_MODULE_PART_RE.match(module) and _FUNC_PART_RE.match(func))
