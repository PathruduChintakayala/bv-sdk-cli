
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Mapping, Sequence

import yaml


SEMVER_PATTERN = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-[0-9A-Za-z-.]+)?(?:\+[0-9A-Za-z-.]+)?$")


def bump_semver(version: str, part: str) -> str:
	"""Return a bumped SemVer string.

	Rules:
	- Accepts SemVer strings validated by SEMVER_PATTERN.
	- Bumps MAJOR/MINOR/PATCH as requested.
	- Drops any pre-release/build metadata on bump for determinism.
	"""
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
	workdir: Path | None = None
	default: bool = False

	def validate(self) -> None:
		errors: List[str] = []
		if not self.name:
			errors.append("entrypoint 'name' is required")
		if not self.command:
			errors.append(f"entrypoint '{self.name or '<unnamed>'}' is missing 'command'")
		if errors:
			raise ValueError("; ".join(errors))

	def to_mapping(self) -> Mapping:
		data: dict[str, object] = {
			"name": self.name,
			"command": self.command,
		}
		if self.workdir:
			data["workdir"] = self.workdir.as_posix()
		if self.default:
			data["default"] = True
		return data


@dataclass
class ProjectConfig:
	name: str
	version: str
	entrypoints: List[EntryPoint]
	venv_dir: Path

	def validate(self, project_root: Path | None = None) -> None:
		errors: List[str] = []
		if not self.name:
			errors.append("project.name is required")
		if not self.version:
			errors.append("project.version is required")
		elif not SEMVER_PATTERN.match(self.version):
			errors.append("project.version must be SemVer (e.g., 1.2.3, 1.2.3-alpha.1)")

		if not self.entrypoints:
			errors.append("project.entrypoints must include at least one entrypoint")
		else:
			default_count = 0
			for entry in self.entrypoints:
				entry.validate()
				if entry.default:
					default_count += 1
				if entry.workdir and project_root:
					resolved = (project_root / entry.workdir).resolve()
					if not resolved.exists():
						errors.append(f"workdir for entrypoint '{entry.name}' does not exist: {resolved}")
			if default_count == 0:
				errors.append("one entrypoint must be marked default")
			elif default_count > 1:
				errors.append("only one entrypoint may be marked default")

		if errors:
			raise ValueError("; ".join(errors))

	def to_mapping(self) -> Mapping:
		return {
			"name": self.name,
			"version": self.version,
			"entrypoints": [entry.to_mapping() for entry in self.entrypoints],
			"venv_dir": self.venv_dir.as_posix(),
		}


class ProjectConfigLoader:
	"""Loads bvproject.yaml into structured config objects without side effects."""

	def __init__(self, config_path: Path) -> None:
		self.config_path = config_path

	def load(self) -> ProjectConfig:
		if not self.config_path.exists():
			raise FileNotFoundError(f"Config not found at {self.config_path}")

		with self.config_path.open("r", encoding="utf-8") as handle:
			raw = yaml.safe_load(handle) or {}

		if not isinstance(raw, Mapping):
			raise ValueError("Configuration root must be a mapping")

		name = self._expect_scalar(raw, "name")
		version = self._expect_scalar(raw, "version")

		entrypoints_data = raw.get("entrypoints", [])
		if not isinstance(entrypoints_data, Sequence):
			raise ValueError("entrypoints must be a list")

		entrypoints: List[EntryPoint] = []
		for idx, item in enumerate(entrypoints_data):
			if not isinstance(item, Mapping):
				raise ValueError(f"project.entrypoints[{idx}] must be a mapping")
			entrypoints.append(
				EntryPoint(
					name=str(item.get("name")) if item.get("name") is not None else "",
					command=str(item.get("command")) if item.get("command") is not None else "",
					workdir=Path(item["workdir"]) if item.get("workdir") else None,
					default=bool(item.get("default", False)),
				)
			)

		venv_dir_raw = raw.get("venv_dir", ".venv")
		if not isinstance(venv_dir_raw, (str, Path)):
			raise ValueError("venv_dir must be a string path")
		venv_dir = Path(venv_dir_raw)

		config = ProjectConfig(
			name=str(name),
			version=str(version),
			entrypoints=entrypoints,
			venv_dir=venv_dir,
		)
		# Validate without hitting filesystem unless project_root is provided later
		config.validate(project_root=None)
		return config

	@staticmethod
	def _expect_mapping(container: Mapping, key: str) -> Mapping:
		value = container.get(key)
		if not isinstance(value, Mapping):
			raise ValueError(f"Missing or invalid '{key}' section; expected mapping")
		return value

	@staticmethod
	def _expect_scalar(container: Mapping, key: str) -> str:
		value = container.get(key)
		if value is None:
			raise ValueError(f"Missing required field '{key}'")
		return str(value)
