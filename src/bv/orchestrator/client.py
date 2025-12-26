
from __future__ import annotations

from pathlib import Path

from bv.project.config import ProjectConfig


class OrchestratorClient:
	"""Placeholder client for orchestrator validation/publish."""

	def validate_project(self, config: ProjectConfig) -> None:
		if not config.entrypoints:
			raise ValueError("At least one entrypoint is required before publishing")

	def validate_package(self, package_path: Path) -> None:
		if not package_path.exists():
			raise FileNotFoundError(f"Package not found: {package_path}")

	def publish(self, package_path: Path) -> None:
		self.validate_package(package_path)
		# Network call placeholder: integrate with real orchestrator API here.
