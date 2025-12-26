
from __future__ import annotations

import importlib
import sys
from pathlib import Path
from typing import Iterable, List, Optional

import yaml

from bv.project.config import EntryPoint, ProjectConfig, ProjectConfigLoader


class EntrypointRegistry:
	"""Manages entrypoints and persists changes to bvproject.yaml."""

	def __init__(self, config_path: Path, config: Optional[ProjectConfig] = None) -> None:
		self.config_path = config_path
		self.loader = ProjectConfigLoader(config_path)
		self._config = config or self.loader.load()
		self.project_root = config_path.parent.resolve()

	@property
	def entrypoints(self) -> List[EntryPoint]:
		return list(self._config.entrypoints)

	@property
	def names(self) -> List[str]:
		return [entry.name for entry in self._config.entrypoints]

	def add(self, name: str, command: str, workdir: Optional[Path], set_default: bool = False) -> None:
		if any(entry.name == name for entry in self._config.entrypoints):
			raise ValueError(f"Entrypoint '{name}' already exists")

		self._validate_import_target(command, self.project_root)

		has_default = any(e.default for e in self._config.entrypoints)
		should_be_default = set_default or not has_default
		entry = EntryPoint(name=name, command=command, workdir=workdir, default=should_be_default)
		if should_be_default:
			for existing in self._config.entrypoints:
				existing.default = False
		self._config.entrypoints.append(entry)
		self._persist()

	def set_default(self, name: str) -> None:
		found = False
		for entry in self._config.entrypoints:
			if entry.name == name:
				entry.default = True
				found = True
			else:
				entry.default = False
		if not found:
			raise KeyError(f"Entrypoint '{name}' is not defined")
		self._persist()

	def validate(self, project_root: Path) -> None:
		project_root = project_root.resolve()
		self._config.validate(project_root=project_root)
		errors: List[str] = []
		for entry in self._config.entrypoints:
			try:
				self._validate_import_target(entry.command, project_root)
			except ValueError as exc:
				errors.append(str(exc))
			workdir = entry.workdir
			if workdir:
				resolved = (project_root / workdir).resolve()
				if not resolved.exists():
					errors.append(f"Workdir for entrypoint '{entry.name}' does not exist: {resolved}")
		if errors:
			raise ValueError("; ".join(errors))

	def get(self, name: str) -> EntryPoint:
		for entry in self._config.entrypoints:
			if entry.name == name:
				return entry
		raise KeyError(f"Entrypoint '{name}' is not defined")

	def list_names(self) -> List[str]:
		return self.names

	def _persist(self) -> None:
		# Validate config prior to write (without touching filesystem beyond config file itself)
		self._config.validate(project_root=None)

		data = self._config.to_mapping()
		tmp_path = self.config_path.with_suffix(self.config_path.suffix + ".tmp")
		self.config_path.parent.mkdir(parents=True, exist_ok=True)
		with tmp_path.open("w", encoding="utf-8") as handle:
			yaml.safe_dump(data, handle, sort_keys=False)
		tmp_path.replace(self.config_path)

	@staticmethod
	def _validate_import_target(target: str, project_root: Path | None) -> None:
		if ":" not in target:
			raise ValueError("Entrypoint command must be in 'module:function' format")
		module_name, func_name = target.split(":", 1)
		if not module_name or not func_name:
			raise ValueError("Entrypoint command requires both module and function")

		added_path = False
		project_root = project_root.resolve() if project_root else None
		try:
			if project_root:
				root_str = str(project_root)
				if root_str not in sys.path:
					sys.path.insert(0, root_str)
					added_path = True
			module = importlib.import_module(module_name)
		except Exception as exc:  # pragma: no cover - import errors are surfaced
			raise ValueError(f"Cannot import module '{module_name}': {exc}") from exc
		finally:
			if added_path and project_root:
				try:
					sys.path.remove(str(project_root))
				except ValueError:
					pass
		if not hasattr(module, func_name):
			raise ValueError(f"Function '{func_name}' not found in module '{module_name}'")
