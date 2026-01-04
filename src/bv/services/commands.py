from __future__ import annotations

import importlib
import json
import os
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

import yaml

from bv.project.config import ProjectConfigLoader, bump_semver, EntryPoint
from bv.validators.project_validator import ProjectValidator
from bv.tools.lock_generator import RequirementsLockGenerator


INIT_BVPROJECT_TEMPLATE = """project:
  name: {project_name}
  version: 1.0.0
  description: A simple BV project
  entrypoints:
    - name: main
      command: main:main
      default: true
  venv_dir: .venv
  python_version: "{python_version}"
  dependencies: ["bv-runtime"]
"""

INIT_MAIN_TEMPLATE = '''"""
Main entry point for BV project.
Define your application logic in the main() function.
"""


def main():
    """
    Main function - entry point for project execution.
    Add your code logic here.
    """
    print("Hello from BV Project!")


if __name__ == "__main__":
    main()
'''


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def init_project(
    project_name: str,
    python_version: str = "3.8",
    keep_main: bool = False,
) -> None:
    """Initialize a project in the current directory with bvproject.yaml and main.py."""
    import os
    project_root = Path(os.getcwd()).resolve()
    
    # Check if bvproject.yaml already exists
    if (project_root / "bvproject.yaml").exists():
        raise ValueError(f"Project already initialized: bvproject.yaml exists in {project_root}")

    # bvproject.yaml
    _atomic_write(
        project_root / "bvproject.yaml",
        INIT_BVPROJECT_TEMPLATE.format(project_name=project_name, python_version=python_version),
    )

    # main.py (respect --keep-main)
    main_path = project_root / "main.py"
    if not (keep_main and main_path.exists()):
        _atomic_write(main_path, INIT_MAIN_TEMPLATE)

    # Create dist folder
    dist_dir = project_root / "dist"
    dist_dir.mkdir(exist_ok=True)


@dataclass
class ValidationResult:
    ok: bool
    errors: List[str]
    warnings: List[str]


def validate_project(config_path: Path, project_root: Path) -> ValidationResult:
    validator = ProjectValidator(str(project_root))
    ok, errors, warnings = validator.validate_all()
    return ValidationResult(ok=ok, errors=errors, warnings=warnings)


def build_package(config_path: Path, output: Optional[Path], dry_run: bool) -> Path:
    """Build a .bvpackage containing main.py, bvproject.yaml, requirements.lock."""
    config_path = config_path.resolve()
    project_root = config_path.parent

    result = validate_project(config_path=config_path, project_root=project_root)
    if not result.ok:
        raise ValueError("Validation failed:\n" + "\n".join(result.errors))

    cfg = ProjectConfigLoader(config_path).load()

    target = output or Path("dist") / f"{cfg.name}-{cfg.version}.bvpackage"
    target = target.with_suffix(".bvpackage")
    if dry_run:
        return target

    # Generate requirements.lock from project dependencies
    lock_path = project_root / "requirements.lock"
    deps = cfg.dependencies or []
    RequirementsLockGenerator().generate(str(project_root), deps)

    with zipfile.ZipFile(target, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        _write_bytes(archive, "bvproject.yaml", (project_root / "bvproject.yaml").read_bytes())
        _write_bytes(archive, "main.py", (project_root / "main.py").read_bytes())
        _write_bytes(archive, "requirements.lock", lock_path.read_bytes())
        
        default_entry = next((e for e in cfg.entrypoints if e.default), cfg.entrypoints[0]) if cfg.entrypoints else None
        entrypoint_cmd = default_entry.command if default_entry else ""
        
        manifest = {
            "name": cfg.name,
            "version": cfg.version,
            "entrypoint": entrypoint_cmd,
            "venv": cfg.venv_dir.as_posix(),
            "python_version": cfg.python_version,
        }
        _write_bytes(archive, "manifest.json", json.dumps(manifest, indent=2).encode("utf-8"))

        # Also write entry-points.json for consistency with PackageBuilder
        entry_points_data = {
            "entryPoints": [
                {
                    "name": e.name,
                    "filePath": e.command.split(":")[0].replace(".", "/") + ".py" if ":" in e.command else e.command,
                    "function": e.command.split(":")[1] if ":" in e.command else "",
                    "type": "agent",
                    "default": e.default
                } for e in cfg.entrypoints
            ]
        }
        _write_bytes(archive, "entry-points.json", json.dumps(entry_points_data, indent=2).encode("utf-8"))

    return target


def publish_package(config_path: Path, publish_dir: Path, dry_run: bool, bump: str = "patch") -> Path:
    """Validate, bump version, generate lock, and copy package to publish dir."""
    config_path = config_path.resolve()
    project_root = config_path.parent

    # Validate
    result = validate_project(config_path=config_path, project_root=project_root)
    if not result.ok:
        raise ValueError("Validation failed:\n" + "\n".join(result.errors))

    cfg = ProjectConfigLoader(config_path).load()

    # Bump version
    next_version = bump_semver(cfg.version, bump)
    cfg.version = next_version
    _atomic_write(config_path, yaml.safe_dump(cfg.to_mapping(), sort_keys=False))

    # Build package (this will generate requirements.lock)
    package_path = build_package(config_path=config_path, output=None, dry_run=dry_run)
    if dry_run:
        return package_path

    dest_dir = publish_dir / cfg.name / cfg.version
    dest_dir.mkdir(parents=True, exist_ok=True)
    destination = dest_dir / package_path.name
    if destination.exists():
        destination.unlink()
    destination.write_bytes(package_path.read_bytes())
    return destination


def run_project(config_path: Path, entrypoint_name: Optional[str] = None) -> object:
    """Run entrypoint locally (best-effort)."""
    config_path = config_path.resolve()
    project_root = config_path.parent
    cfg = ProjectConfigLoader(config_path).load()

    if entrypoint_name:
        entry = next((e for e in cfg.entrypoints if e.name == entrypoint_name), None)
        if not entry:
            raise ValueError(f"Entrypoint '{entrypoint_name}' not found")
    else:
        entry = next((e for e in cfg.entrypoints if e.default), None)
        if not entry and cfg.entrypoints:
            entry = cfg.entrypoints[0]

    if not entry:
        raise ValueError("No entrypoint configured")

    # Set BV_SDK_RUN environment variable to allow runtime access
    os.environ["BV_SDK_RUN"] = "1"

    if ":" in entry.command:
        module_part, func_name = entry.command.split(":")
        module_name = module_part.replace(".py", "")

        sys.path.insert(0, str(project_root))
        try:
            module = importlib.import_module(module_name)
            func = getattr(module, func_name)
            if not callable(func):
                raise TypeError(f"{entry.command} is not callable")
            return func()
        finally:
            try:
                sys.path.remove(str(project_root))
            except ValueError:
                pass
    else:
        # Script mode
        script_path = project_root / entry.command
        if not script_path.exists():
            raise FileNotFoundError(f"Script not found: {script_path}")
        
        import runpy
        # run_path executes the file and returns the globals dictionary.
        # We add project_root to sys.path so the script can import local modules.
        sys.path.insert(0, str(project_root))
        try:
            return runpy.run_path(str(script_path), run_name="__main__")
        finally:
            try:
                sys.path.remove(str(project_root))
            except ValueError:
                pass


def _write_bytes(archive: zipfile.ZipFile, arcname: str, data: bytes) -> None:
    archive.writestr(arcname, data)
