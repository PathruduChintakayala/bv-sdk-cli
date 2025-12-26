
from __future__ import annotations

import json
import zipfile
from pathlib import Path
from typing import Iterable, List, Sequence

from bv.project.config import EntryPoint, ProjectConfig
from bv.venv.manager import VenvManager


EXCLUDE_DIRS = {".venv", "__pycache__", ".git", "dist"}


class PackageBuilder:
	"""Builds a .bvpackage archive from a project workspace."""

	def __init__(self, project_root: Path) -> None:
		self.project_root = project_root

	def build(
		self,
		output_path: Path,
		config: ProjectConfig,
		sources: Sequence[Path],
		venv_manager: VenvManager,
		dry_run: bool = False,
	) -> Path:
		if not output_path.name.endswith(".bvpackage"):
			output_path = output_path.with_name(output_path.name + ".bvpackage")
		config.validate(project_root=self.project_root)

		manifest = self._manifest(config)
		requirements_lock = self.project_root / "requirements.lock"

		if dry_run:
			return output_path

		# Generate lock inside venv
		venv_manager.freeze(requirements_lock)

		output_path.parent.mkdir(parents=True, exist_ok=True)
		tmp_output = output_path.with_suffix(".tmp")
		if tmp_output.exists():
			tmp_output.unlink()

		try:
			with zipfile.ZipFile(tmp_output, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
				self._write_json(archive, "manifest.json", manifest)
				self._write_json(archive, "entry-points.json", self._entrypoints(config.entrypoints))
				self._write_file(archive, requirements_lock, Path("requirements.lock"))
				self._write_sources(archive, sources)
			tmp_output.replace(output_path)
		except Exception:
			if tmp_output.exists():
				tmp_output.unlink()
			raise

		return output_path

	def _write_sources(self, archive: zipfile.ZipFile, sources: Sequence[Path]) -> None:
		seen = set()
		reserved = {"manifest.json", "entry-points.json", "requirements.lock"}
		all_files: List[Path] = []
		for rel in sources:
			rel = Path(rel)
			if rel in seen:
				continue
			seen.add(rel)
			absolute = (self.project_root / rel).resolve()
			if not absolute.exists():
				raise FileNotFoundError(f"Package source missing: {absolute}")

			if absolute.is_dir():
				for file_path in absolute.rglob("*"):
					if file_path.is_dir():
						continue
					if self._is_excluded(file_path):
						continue
					all_files.append(file_path)
			else:
				if self._is_excluded(absolute):
					continue
				all_files.append(absolute)

		for file_path in sorted(all_files, key=lambda p: p.relative_to(self.project_root).as_posix()):
			arcname = file_path.relative_to(self.project_root).as_posix()
			if arcname in reserved:
				continue
			self._write_file_deterministic(archive, file_path, arcname)

	def _write_json(self, archive: zipfile.ZipFile, name: str, data: dict) -> None:
		self._write_bytes(archive, name, json.dumps(data, indent=2).encode("utf-8"))

	def _write_file(self, archive: zipfile.ZipFile, source: Path, arcname: Path) -> None:
		self._write_file_deterministic(archive, source, arcname.as_posix())

	def _write_bytes(self, archive: zipfile.ZipFile, arcname: str, content: bytes) -> None:
		info = zipfile.ZipInfo(arcname)
		info.date_time = (2020, 1, 1, 0, 0, 0)
		info.compress_type = zipfile.ZIP_DEFLATED
		archive.writestr(info, content)

	def _write_file_deterministic(self, archive: zipfile.ZipFile, source: Path, arcname: str) -> None:
		data = source.read_bytes()
		self._write_bytes(archive, arcname, data)

	def _is_excluded(self, path: Path) -> bool:
		for part in path.relative_to(self.project_root).parts:
			if part in EXCLUDE_DIRS:
				return True
		return False

	@staticmethod
	def _manifest(config: ProjectConfig) -> dict:
		return {
			"name": config.name,
			"version": config.version,
			"venv": config.venv_dir.as_posix(),
		}

	@staticmethod
	def _entrypoints(entries: List[EntryPoint]) -> dict:
		items = []
		for entry in entries:
			module_name, func_name = (entry.command.split(":", 1) + [""])[:2]
			file_path = Path(*module_name.split(".")).with_suffix(".py").as_posix() if module_name else ""
			items.append(
				{
					"name": entry.name,
					"filePath": file_path,
					"function": func_name,
					"type": "agent",
					"default": entry.default,
				}
			)
		return {"entryPoints": items}
