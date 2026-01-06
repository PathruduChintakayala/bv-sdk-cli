from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import List, Tuple

import yaml

from bv.project.config import DEFAULT_PROJECT_TYPE, PROJECT_TYPES

ENTRYPOINT_PATTERN = re.compile(r"^(?:[A-Za-z0-9_\.]+:[A-Za-z_][A-Za-z0-9_]*|.*\.py)$")
SEMVER_PATTERN = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-[0-9A-Za-z-.]+)?(?:\+[0-9A-Za-z-.]+)?$")
# Accept 3.8, 3.11, or 3.11.1 style versions
PY_VERSION_PATTERN = re.compile(r"^\d+\.\d+(?:\.\d+)?$")
NAME_PATTERN = re.compile(r"^[a-zA-Z0-9_-]+$")


class ProjectValidator:
    """Comprehensive project validation before publishing."""

    def __init__(self, project_path: str):
        self.project_path = Path(project_path)
        self.errors: List[str] = []
        self.warnings: List[str] = []

    def validate_all(self) -> Tuple[bool, List[str], List[str]]:
        self.errors = []
        self.warnings = []

        self._validate_file_existence()
        if self.errors:
            return False, self.errors, self.warnings

        config = self._validate_bvproject_yaml()
        if self.errors or config is None:
            return False, self.errors, self.warnings

        self._validate_main_py(config)
        self._validate_dependencies(config)
        self._validate_project_metadata(config)

        return len(self.errors) == 0, self.errors, self.warnings

    # --- individual checks ---
    def _validate_file_existence(self) -> None:
        if not (self.project_path / "bvproject.yaml").exists():
            self.errors.append("ERROR: bvproject.yaml not found in project root")
        if not (self.project_path / "main.py").exists():
            self.errors.append("ERROR: main.py not found in project root")

    def _validate_bvproject_yaml(self):
        try:
            with open(self.project_path / "bvproject.yaml", "r", encoding="utf-8") as f:
                config = yaml.safe_load(f)
        except yaml.YAMLError as e:
            self.errors.append(f"ERROR: Invalid YAML syntax in bvproject.yaml: {e}")
            return None

        if not config or "project" not in config or not isinstance(config.get("project"), dict):
            self.errors.append("ERROR: bvproject.yaml must contain 'project' mapping")
            return None

        project = config["project"]
        required = ["name", "version"]
        for field in required:
            if field not in project or project[field] in (None, ""):
                self.errors.append(f"ERROR: Missing required field project.{field}")

        raw_type = project.get("type")
        if raw_type is None or str(raw_type).strip() == "":
            self.warnings.append("WARNING: project.type is missing; defaulting to 'rpa' for backward compatibility")
            project["type"] = DEFAULT_PROJECT_TYPE
        else:
            project_type = str(raw_type).strip().lower()
            if project_type not in PROJECT_TYPES:
                self.errors.append("ERROR: project.type must be one of: rpa, agent")
            else:
                project["type"] = project_type

        # Support both new format (entrypoints) and legacy format (entrypoint)
        entrypoints = project.get("entrypoints")
        entrypoint = project.get("entrypoint")
        
        if entrypoints:
            # New format: entrypoints is a list
            if not isinstance(entrypoints, list) or len(entrypoints) == 0:
                self.errors.append("ERROR: project.entrypoints must be a non-empty list")
            else:
                defaults = [e for e in entrypoints if isinstance(e, dict) and e.get("default")]
                if len(defaults) != 1:
                    self.errors.append("ERROR: project.entrypoints must have exactly one entrypoint marked as default")
                for i, ep in enumerate(entrypoints):
                    if not isinstance(ep, dict):
                        self.errors.append(f"ERROR: project.entrypoints[{i}] must be a mapping")
                        continue
                    if "name" not in ep or not ep.get("name"):
                        self.errors.append(f"ERROR: project.entrypoints[{i}].name is required")
                    if "command" not in ep or not ep.get("command"):
                        self.errors.append(f"ERROR: project.entrypoints[{i}].command is required")
                    elif not ENTRYPOINT_PATTERN.match(str(ep.get("command", ""))):
                        self.errors.append(f"ERROR: project.entrypoints[{i}].command must be like 'main:main' or end with .py")
        elif entrypoint:
            # Legacy format: entrypoint is a string
            if not isinstance(entrypoint, str) or not entrypoint.strip():
                self.errors.append("ERROR: project.entrypoint must be a non-empty string")
            elif not ENTRYPOINT_PATTERN.match(entrypoint.strip()):
                self.errors.append("ERROR: project.entrypoint must be like 'main:main' or end with .py")
        else:
            self.errors.append("ERROR: Missing required field project.entrypoint or project.entrypoints")

        if "python_version" in project:
            pyv = str(project["python_version"]).strip()
            # Allow empty/omitted python_version; only validate if provided
            if pyv and not PY_VERSION_PATTERN.match(pyv):
                self.errors.append("ERROR: project.python_version must be like '3.8' or '3.11.1'")

        return config

    def _validate_main_py(self, config: dict) -> None:
        main_path = self.project_path / "main.py"
        try:
            source = main_path.read_text(encoding="utf-8")
            ast.parse(source)
        except Exception as e:
            self.errors.append(f"ERROR: Syntax error in main.py: {e}")
            return

        project = config.get("project", {})
        # Support both new format (entrypoints) and legacy format (entrypoint)
        entrypoints = project.get("entrypoints")
        entrypoint = project.get("entrypoint", "")
        
        if entrypoints:
            # New format: validate the default entrypoint
            defaults = [e for e in entrypoints if isinstance(e, dict) and e.get("default")]
            if defaults:
                ep = str(defaults[0].get("command", ""))
            else:
                # No default found, skip validation (error already reported in _validate_bvproject_yaml)
                return
        else:
            # Legacy format
            ep = entrypoint
        
        if not ep:
            return
        
        if ep.endswith(".py"):
            # Script execution model - file existence checked in _validate_file_existence 
            # or implicitly via main.py check.
            return

        if ":" not in ep:
            return  # Not a module:function format, skip function validation

        file_part, method = ep.split(":", 1)
        if file_part.endswith(".py"):
            file_part = file_part[:-3]
        if file_part not in ("main", "main.py", ""):
            self.warnings.append(f"WARNING: Entrypoint file '{file_part}' is not main.py; ensure it exists.")

        if not self._function_exists(source, method):
            self.errors.append(f"ERROR: Method '{method}' not found in main.py")

        if 'if __name__ == "__main__":' not in source:
            self.warnings.append("WARNING: main.py should include an '__main__' guard.")

    def _function_exists(self, source: str, func_name: str) -> bool:
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return False
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == func_name:
                return True
        return False

    def _validate_dependencies(self, config: dict) -> None:
        deps = config.get("project", {}).get("dependencies", [])
        if deps is None:
            deps = []
        if not isinstance(deps, list):
            self.errors.append("ERROR: project.dependencies must be a list")
            return
        for dep in deps:
            if not isinstance(dep, str):
                self.errors.append(f"ERROR: Invalid dependency '{dep}'; must be a string")

    def _validate_project_metadata(self, config: dict) -> None:
        project = config.get("project", {})
        name = str(project.get("name") or "")
        version = str(project.get("version") or "")
        if not NAME_PATTERN.match(name):
            self.errors.append("ERROR: project.name must be alphanumeric/hyphen/underscore")
        if not SEMVER_PATTERN.match(version):
            self.warnings.append("WARNING: project.version should follow SemVer (e.g., 1.0.0)")

