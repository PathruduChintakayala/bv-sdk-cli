from __future__ import annotations

import importlib
import inspect
import json
import os
import shutil
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

import yaml

from bv.entrypoints.registry import EntrypointRegistry
from bv.packaging.builder import PackageBuilder
from bv.project.config import EntryPoint, ProjectConfig, ProjectConfigLoader, bump_semver
from bv.venv.manager import VenvManager


def _atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        handle.write(content)
    tmp.replace(path)


def _atomic_write_yaml(path: Path, data: dict) -> None:
    _atomic_write_text(path, yaml.safe_dump(data, sort_keys=False))


def _resolve_project_root(config_path: Path) -> Path:
    if config_path.is_absolute():
        return config_path.parent.resolve()
    return Path.cwd().resolve()


def init_project(
    config_path: Path = Path("bvproject.yaml"),
    python_executable: str | None = None,
    project_name: str | None = None,
) -> None:
    """Initialize a project for root-level automations (config, venv, templates)."""
    project_root = _resolve_project_root(config_path)
    config_path = config_path if config_path.is_absolute() else (project_root / config_path)

    if config_path.exists():
        raise FileExistsError(
            f"Project already initialized: config exists at {config_path}. Remove it to re-initialize."
        )

    project_root.mkdir(parents=True, exist_ok=True)
    (project_root / "dist").mkdir(parents=True, exist_ok=True)

    resolved_name = project_name if project_name is not None else Path.cwd().name
    if not resolved_name:
        raise ValueError("Project name could not be determined; pass --name explicitly")

    config = ProjectConfig(
        name=resolved_name,
        version="0.0.0",
        venv_dir=Path(".venv"),
        entrypoints=[
            EntryPoint(
                name="main",
                command="main:main",
                workdir=None,
                default=True,
            )
        ],
    )
    config.validate(project_root=project_root)

    venv_path = project_root / config.venv_dir
    venv_preexisting = venv_path.exists()
    created_files: list[Path] = []

    main_py = (
        "from __future__ import annotations\n\n"
        "from typing import Any\n\n"
        "def main(input: dict[str, Any] | None = None) -> dict[str, Any]:\n"
        "    data = input or {}\n"
        "    name = str(data.get(\"name\", \"World\"))\n"
        "    return {\"result\": f\"Hello {name}\"}\n"
    )

    entry_points_json = {
        "entryPoints": [
            {
                "name": "main",
                "filePath": "main.py",
                "function": "main",
                "type": "agent",
                "default": True,
            }
        ]
    }

    bindings_json: dict = {}

    pyproject_content = (
        "[project]\n"
        "requires-python = \">=3.11\"\n"
        "dependencies = []\n"
    )

    try:
        _atomic_write_yaml(config_path, dict(config.to_mapping()))
        created_files.append(config_path)
        _atomic_write_text(project_root / "main.py", main_py)
        created_files.append(project_root / "main.py")
        _atomic_write_text(project_root / "entry-points.json", json.dumps(entry_points_json, indent=2) + "\n")
        created_files.append(project_root / "entry-points.json")
        _atomic_write_text(project_root / "bindings.json", json.dumps(bindings_json, indent=2) + "\n")
        created_files.append(project_root / "bindings.json")
        _atomic_write_text(project_root / "pyproject.toml", pyproject_content)
        created_files.append(project_root / "pyproject.toml")

        VenvManager(venv_path).create(python_executable=python_executable)
    except Exception:
        for path in created_files:
            try:
                path.unlink()
            except Exception:
                pass
        if not venv_preexisting and venv_path.exists():
            try:
                shutil.rmtree(venv_path)
            except Exception:
                pass
        raise


def add_entrypoint(
    config_path: Path,
    name: str,
    command: str,
    workdir: Optional[Path],
    set_default: bool,
) -> None:
    """Add a new entrypoint to the project config."""
    registry = EntrypointRegistry(config_path)
    registry.add(name=name, command=command, workdir=workdir, set_default=set_default)


def list_entrypoints(config_path: Path) -> List[str]:
    """List entrypoint names from the project config."""
    registry = EntrypointRegistry(config_path)
    return registry.list_names()


def set_default_entrypoint(config_path: Path, name: str) -> None:
    """Mark an entrypoint as default."""
    registry = EntrypointRegistry(config_path)
    registry.set_default(name)


@dataclass
class ValidationResult:
    ok: bool
    errors: List[str]
    warnings: List[str]
    config: Optional[ProjectConfig]


def validate_project(
    config_path: Path,
    project_root: Path,
) -> ValidationResult:
    """Validate bvproject.yaml, SemVer, and entrypoints import targets."""
    errors: List[str] = []
    warnings: List[str] = []
    cfg: Optional[ProjectConfig] = None

    if not config_path.exists():
        errors.append(f"Config not found at {config_path}")
        return ValidationResult(ok=False, errors=errors, warnings=warnings, config=None)

    try:
        cfg = ProjectConfigLoader(config_path).load()
    except Exception as exc:
        errors.append(f"Invalid config: {exc}")
        return ValidationResult(ok=False, errors=errors, warnings=warnings, config=None)

    try:
        EntrypointRegistry(config_path, cfg).validate(project_root)
    except Exception as exc:
        errors.append(f"Entrypoints invalid: {exc}")

    return ValidationResult(ok=not errors, errors=errors, warnings=warnings, config=cfg)


def build_package(
    config_path: Path,
    output: Optional[Path],
    include: Optional[List[Path]],
    dry_run: bool,
) -> Path:
    """Build a .bvpackage from the project workspace."""
    config_path = config_path.resolve()
    validation = validate_project(config_path=config_path, project_root=config_path.parent)
    if not validation.ok or not validation.config:
        raise ValueError("Validation failed: " + "; ".join(validation.errors))
    cfg = validation.config
    registry = EntrypointRegistry(config_path, cfg)
    registry.validate(project_root=config_path.parent)
    venv_manager = VenvManager(config_path.parent / cfg.venv_dir)
    venv_manager.ensure(create_if_missing=False)

    package_root = config_path.parent
    builder = PackageBuilder(project_root=package_root)

    sources: set[Path] = {
        Path("main.py"),
        Path("entry-points.json"),
        Path("bindings.json"),
        Path("pyproject.toml"),
        config_path.relative_to(package_root),
    }
    for entry in cfg.entrypoints:
        module_name, _ = (entry.command.split(":", 1) + [""])[:2]
        if module_name:
            sources.add(Path(*module_name.split(".")).with_suffix(".py"))
        if entry.workdir:
            sources.add(entry.workdir)
    if include:
        for item in include:
            sources.add(item)

    target = output or Path("dist") / f"{cfg.name}-{cfg.version}"
    return builder.build(
        target,
        config=cfg,
        sources=sorted(sources, key=lambda p: p.as_posix()),
        venv_manager=venv_manager,
        dry_run=dry_run,
    )


def publish_package(
    config_path: Path,
    package_path: Optional[Path],
    publish_dir: Path,
    include: Optional[List[Path]],
    move: bool,
    overwrite: bool,
    bump: str,
    dry_run: bool,
) -> Path:
    """Finalize a .bvpackage locally by copying/moving into a publish directory."""

    config_path = config_path.resolve()
    validation = validate_project(config_path=config_path, project_root=config_path.parent)
    if not validation.ok or not validation.config:
        raise ValueError("Validation failed: " + "; ".join(validation.errors))
    cfg = validation.config

    next_version = bump_semver(cfg.version, bump)

    if dry_run:
        effective_name = cfg.name
        effective_version = next_version
        effective_package_path = package_path
        if effective_package_path is None:
            effective_package_path = Path("dist") / f"{effective_name}-{effective_version}.bvpackage"
        effective_package_path = effective_package_path.with_suffix(".bvpackage")
        return (publish_dir / effective_name / effective_version / effective_package_path.name).resolve()

    # Persist bumped version before building/publishing
    cfg.version = next_version
    _atomic_write_yaml(config_path, dict(cfg.to_mapping()))

    # Reload from disk to ensure build uses the persisted version exactly
    cfg = ProjectConfigLoader(config_path).load()

    # Build if package is absent
    if package_path is None or not package_path.exists():
        package_path = build_package(
            config_path=config_path,
            output=package_path,
            include=include,
            dry_run=dry_run,
        )
    if not package_path.exists():
        raise FileNotFoundError(f"Package not found at {package_path}")

    if not package_path.suffix.endswith(".bvpackage"):
        raise ValueError("Publish requires a .bvpackage artifact")

    _validate_package_file(package_path, expected_name=cfg.name, expected_version=cfg.version)

    destination_dir = publish_dir / cfg.name / cfg.version
    destination_dir.mkdir(parents=True, exist_ok=True)
    destination = destination_dir / package_path.name
    if destination.exists() and not overwrite:
        raise FileExistsError(
            f"Published artifact already exists: {destination}. Use --overwrite to replace."
        )

    if move:
        # shutil.move handles cross-filesystem moves safely
        tmp_dest = destination.with_suffix(destination.suffix + ".tmp") if destination.exists() else destination
        final_dest = destination
        try:
            if destination.exists():
                destination.unlink()
            shutil.move(str(package_path), str(tmp_dest))
            tmp_dest.replace(final_dest)
        except Exception:
            if tmp_dest.exists():
                try:
                    tmp_dest.unlink()
                except Exception:
                    pass
            raise
    else:
        tmp_dest = destination.with_suffix(destination.suffix + ".tmp")
        try:
            shutil.copy2(package_path, tmp_dest)
            tmp_dest.replace(destination)
        except Exception:
            if tmp_dest.exists():
                try:
                    tmp_dest.unlink()
                except Exception:
                    pass
            raise

    return destination


def run_project(
    config_path: Path,
    entry_name: str | None,
    input_path: Path | None,
) -> object:
    """Execute a configured entrypoint locally in-process.

    - Uses project root (config parent) as import root.
    - Calls entrypoint with either no args or one dict arg.
    """
    config_path = config_path.resolve()
    if not config_path.exists():
        raise FileNotFoundError(f"Config not found at {config_path}")

    cfg = ProjectConfigLoader(config_path).load()
    registry = EntrypointRegistry(config_path, cfg)

    selected: EntryPoint | None = None
    if entry_name:
        selected = registry.get(entry_name)
    else:
        for item in cfg.entrypoints:
            if item.default:
                selected = item
                break
    if not selected:
        raise ValueError("No default entrypoint is defined; set one in bvproject.yaml or pass --entry")

    input_data: dict = {}
    if input_path is not None:
        try:
            raw = input_path.read_bytes().decode("utf-8-sig")
        except Exception as exc:
            raise ValueError(f"Unable to read input JSON file '{input_path}': {exc}") from exc
        try:
            parsed = json.loads(raw)
        except Exception as exc:
            raise ValueError(f"Invalid JSON in '{input_path}': {exc}") from exc
        if parsed is None:
            input_data = {}
        elif not isinstance(parsed, dict):
            raise ValueError("Input JSON must be an object (mapping)")
        else:
            input_data = parsed

    command = selected.command
    if ":" not in command:
        raise ValueError("Entrypoint command must be in 'module:function' format")
    module_name, func_name = command.split(":", 1)
    if not module_name or not func_name:
        raise ValueError("Entrypoint command must include both module and function")

    project_root = config_path.parent.resolve()
    added_path = False
    old_bv_sdk_run = os.environ.get("BV_SDK_RUN")
    old_bv_orch_url = os.environ.get("BV_ORCHESTRATOR_URL")
    try:
        os.environ["BV_SDK_RUN"] = "1"

        # If the project declares an orchestrator.url, make it the expected URL for runtime.
        try:
            from bv.project.orchestrator import resolve_orchestrator_url

            expected_url = resolve_orchestrator_url(config_path)
            if expected_url:
                os.environ["BV_ORCHESTRATOR_URL"] = expected_url
        except Exception:
            pass

        root_str = str(project_root)
        if root_str not in sys.path:
            sys.path.insert(0, root_str)
            added_path = True
        try:
            module = importlib.import_module(module_name)
        except Exception as exc:
            raise ImportError(f"Cannot import module '{module_name}' from project root '{project_root}': {exc}") from exc

        if not hasattr(module, func_name):
            raise AttributeError(f"Function '{func_name}' not found in module '{module_name}'")
        func = getattr(module, func_name)
        if not callable(func):
            raise TypeError(f"'{module_name}:{func_name}' is not callable")

        try:
            signature = inspect.signature(func)
        except Exception:
            signature = None

        if signature is None:
            # Best-effort fallback
            return func(input_data) if input_data else func()

        params = list(signature.parameters.values())
        required = [
            p
            for p in params
            if p.default is inspect._empty
            and p.kind not in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD)
        ]

        if input_data:
            if len(required) == 0 and len(params) == 0:
                raise TypeError("Entrypoint does not accept input; remove --input or update the function signature")
            if len(params) == 0:
                raise TypeError("Entrypoint does not accept arguments; provide no input")
            if len(required) > 1 and all(p.kind == inspect.Parameter.POSITIONAL_ONLY for p in required):
                raise TypeError("Entrypoint requires multiple positional arguments; expected 0 or 1")
            return func(input_data)

        # No input provided
        if len(required) == 0 and len(params) == 0:
            return func()
        if len(required) <= 1 and len(params) >= 1:
            return func({})
        raise TypeError("Entrypoint signature must accept 0 args or exactly 1 argument")

    finally:
        if old_bv_sdk_run is None:
            os.environ.pop("BV_SDK_RUN", None)
        else:
            os.environ["BV_SDK_RUN"] = old_bv_sdk_run

        if old_bv_orch_url is None:
            os.environ.pop("BV_ORCHESTRATOR_URL", None)
        else:
            os.environ["BV_ORCHESTRATOR_URL"] = old_bv_orch_url

        if added_path:
            try:
                sys.path.remove(str(project_root))
            except ValueError:
                pass


def _validate_package_file(package_path: Path, expected_name: str, expected_version: str) -> None:
    """Ensure package contains manifest and entrypoints matching config expectations."""
    if not package_path.exists():
        raise FileNotFoundError(f"Package not found: {package_path}")

    try:
        with zipfile.ZipFile(package_path, "r") as archive:
            manifest = _read_json(archive, "manifest.json")
            entrypoints = _read_json(archive, "entry-points.json")
    except Exception as exc:
        raise ValueError(f"Invalid package contents: {exc}") from exc

    name = manifest.get("name") if isinstance(manifest, dict) else None
    version = manifest.get("version") if isinstance(manifest, dict) else None
    if name != expected_name:
        raise ValueError(f"Package name mismatch: expected '{expected_name}', found '{name}'")
    if version != expected_version:
        raise ValueError(f"Package version mismatch: expected '{expected_version}', found '{version}'")

    entries = entrypoints.get("entryPoints") if isinstance(entrypoints, dict) else None
    if not entries:
        raise ValueError("Package entry-points.json missing or empty")
    for idx, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise ValueError(f"Entrypoint at index {idx} is invalid; expected mapping")
        if not entry.get("name") or not entry.get("function"):
            raise ValueError(f"Entrypoint at index {idx} missing name or function")


def _read_json(archive: zipfile.ZipFile, name: str) -> dict:
    with archive.open(name) as handle:
        return json.loads(handle.read().decode("utf-8"))
