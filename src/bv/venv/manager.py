
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


class VenvManager:
	"""Manages a per-project virtual environment and all pip actions within it."""

	def __init__(self, venv_dir: Path) -> None:
		self.venv_dir = venv_dir

	def exists(self) -> bool:
		return (self.venv_dir / self._bin_dir()).exists()

	def create(self, python_executable: str | None = None) -> Path:
		"""Create venv using the specified interpreter (defaults to current)."""
		target = self.venv_dir
		target.parent.mkdir(parents=True, exist_ok=True)
		python = python_executable or sys.executable
		subprocess.run([python, "-m", "venv", str(target), "--without-pip"], check=True)
		# Ensure pip is present and up-to-date inside the venv
		self._run(["-m", "ensurepip", "--upgrade"])
		self._run(["-m", "pip", "install", "--upgrade", "pip"])
		return target

	def ensure(self, create_if_missing: bool = False, python_executable: str | None = None) -> Path:
		if self.exists():
			return self.venv_dir
		if not create_if_missing:
			raise FileNotFoundError(
				f"Virtual environment not found at {self.venv_dir}. Re-run with create_if_missing=True to create it explicitly."
			)
		return self.create(python_executable=python_executable)

	def install(self, requirements: list[str] | None = None, requirements_file: Path | None = None, upgrade_pip: bool = False) -> None:
		"""Install dependencies inside the venv (explicit only)."""
		self.ensure(create_if_missing=False)
		if upgrade_pip:
			self._run(["-m", "pip", "install", "--upgrade", "pip"])
		if requirements_file:
			self._run(["-m", "pip", "install", "-r", str(requirements_file)])
		if requirements:
			self._run(["-m", "pip", "install", *requirements])

	def freeze(self, output: Path) -> None:
		"""Write pip freeze output to a lock file inside the project."""
		self.ensure(create_if_missing=False)
		output.parent.mkdir(parents=True, exist_ok=True)
		result = self._run(["-m", "pip", "freeze"], capture_output=True, text=True)
		output.write_text(result.stdout, encoding="utf-8")

	def python_path(self) -> Path:
		bin_dir = self.venv_dir / self._bin_dir()
		return bin_dir / ("python.exe" if os.name == "nt" else "python")

	def _bin_dir(self) -> str:
		return "Scripts" if os.name == "nt" else "bin"

	def _run(self, args: list[str], capture_output: bool = False, text: bool = False) -> subprocess.CompletedProcess:
		python = self.python_path()
		if not python.exists():
			raise FileNotFoundError(f"Python interpreter not found in venv: {python}")
		return subprocess.run(
			[str(python), *args],
			check=True,
			capture_output=capture_output,
			text=text,
		)
