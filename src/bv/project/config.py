
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Mapping, Optional

import yaml

# Proper SemVer matcher (e.g., 1.2.3, 1.2.3-alpha.1)
SEMVER_PATTERN = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-[0-9A-Za-z-.]+)?(?:\+[0-9A-Za-z-.]+)?$"
)
# Python version like 3.8 or 3.11.1
PY_VERSION_PATTERN = re.compile(r"^\d+\.\d+(?:\.\d+)?$")


def bump_semver(version: str, part: str) -> str:
    """Return a bumped SemVer string."""
    match = SEMVER_PATTERN.match(version or "")
    if not match:
        raise ValueError(f"Invalid SemVer: '{version}'")

    major = int(match.group(1))
    minor = int(match.group(2))
    patch = int(match.group(3))

    if part == "major":
        major += 1
        minor = 0
        patch = 0
    elif part == "minor":
        minor += 1
        patch = 0
    elif part == "patch":
        patch += 1
    else:
        raise ValueError("part must be one of: major, minor, patch")

    return f"{major}.{minor}.{patch}"


@dataclass
class EntryPoint:
    name: str
    command: str
    workdir: Optional[Path] = None
    default: bool = False


@dataclass
class ProjectConfig:
    """Minimal BV project config"""

    name: str
    version: str
    description: str
    entrypoints: List[EntryPoint]
    venv_dir: Path
    python_version: str
    dependencies: List[str]

    def validate(self, project_root: Optional[Path] = None) -> None:
        errors: List[str] = []
        if not self.name:
            errors.append("project.name is required")
        if not self.version:
            errors.append("project.version is required")
        elif not SEMVER_PATTERN.match(self.version):
            errors.append("project.version must be SemVer (e.g., 1.2.3)")
        
        if not self.entrypoints:
            errors.append("at least one entrypoint is required")
        else:
            defaults = [e for e in self.entrypoints if e.default]
            if not defaults:
                errors.append("exactly one entrypoint must be marked default (none found)")
            elif len(defaults) > 1:
                errors.append(f"exactly one entrypoint must be marked default (found {len(defaults)})")
            
            for entry in self.entrypoints:
                if not entry.name:
                    errors.append("entrypoint name is required")
                if not entry.command:
                    errors.append(f"entrypoint '{entry.name}' command is required")
                elif not (":" in entry.command or entry.command.endswith(".py")):
                    errors.append(f"entrypoint '{entry.name}' command must be in 'module:function' format or end with .py")

        if self.python_version:
            if not PY_VERSION_PATTERN.match(self.python_version):
                errors.append("project.python_version must look like 3.8 or 3.11.1")
        if self.dependencies is None:
            self.dependencies = []
        if not isinstance(self.dependencies, list):
            errors.append("project.dependencies must be a list of strings")
        if errors:
            raise ValueError("; ".join(errors))

    def to_mapping(self) -> Mapping:
        entries = []
        for e in self.entrypoints:
            item = {
                "name": e.name,
                "command": e.command,
                "default": e.default
            }
            if e.workdir:
                item["workdir"] = str(e.workdir)
            entries.append(item)

        return {
            "project": {
                "name": self.name,
                "version": self.version,
                "description": self.description,
                "entrypoints": entries,
                "venv_dir": str(self.venv_dir),
                "python_version": self.python_version,
                "dependencies": self.dependencies,
            }
        }


class ProjectConfigLoader:
    """Load minimal bvproject.yaml"""

    def __init__(self, config_path: Path) -> None:
        self.config_path = config_path

    def load(self) -> ProjectConfig:
        if not self.config_path.exists():
            raise FileNotFoundError(f"Config not found at {self.config_path}")

        with self.config_path.open("r", encoding="utf-8") as handle:
            raw = yaml.safe_load(handle) or {}

        if not isinstance(raw, Mapping):
            raise ValueError("Configuration root must be a mapping")

        # Support both flat and 'project:' nested structure
        project = raw.get("project")
        if not isinstance(project, Mapping):
            project = raw

        # Load entrypoints
        entrypoints = []
        raw_entries = project.get("entrypoints")
        if isinstance(raw_entries, list):
            for e in raw_entries:
                if isinstance(e, Mapping):
                    entrypoints.append(EntryPoint(
                        name=str(e.get("name", "")),
                        command=str(e.get("command", "")),
                        workdir=Path(e["workdir"]) if e.get("workdir") else None,
                        default=bool(e.get("default", False))
                    ))
        
        # Legacy single entrypoint support
        legacy_entry = project.get("entrypoint")
        if legacy_entry and not entrypoints:
            entrypoints.append(EntryPoint(
                name="main",
                command=str(legacy_entry),
                default=True
            ))

        cfg = ProjectConfig(
            name=str(project.get("name") or ""),
            version=str(project.get("version") or ""),
            description=str(project.get("description") or ""),
            entrypoints=entrypoints,
            venv_dir=Path(project.get("venv_dir") or ".venv"),
            python_version=str(project.get("python_version") or "3.8"),
            dependencies=list(project.get("dependencies") or []),
        )
        cfg.validate()
        return cfg
