import json
import zipfile
from pathlib import Path

import pytest

from bv.packaging.bvpackage_validator import (
    BVPackageContractError,
    reject_reupload,
    validate_bvpackage_contract_v1,
)


def _write_zip(path: Path, files: dict[str, str]) -> None:
    fixed_dt = (2020, 1, 1, 0, 0, 0)
    with zipfile.ZipFile(path, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name in sorted(files.keys()):
            info = zipfile.ZipInfo(filename=name, date_time=fixed_dt)
            zf.writestr(info, files[name])


def _to_yaml(obj: dict) -> str:
    import yaml

    return yaml.safe_dump(obj, sort_keys=False)


def _valid_files(*, version: str = "0.0.1", multiple_defaults: bool = False) -> dict[str, str]:
    bvproject = {
        "name": "demo_pkg",
        "version": version,
        "entrypoints": [
            {"name": "main", "command": "main:main", "default": True},
        ],
    }

    if multiple_defaults:
        bvproject["entrypoints"].append(
            {"name": "alt", "command": "alt:run", "default": True}
        )

    entry_points = {
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

    if multiple_defaults:
        entry_points["entryPoints"].append(
            {
                "name": "alt",
                "filePath": "alt.py",
                "function": "run",
                "type": "agent",
                "default": True,
            }
        )

    return {
        "bvproject.yaml": _to_yaml(bvproject),
        "entry-points.json": json.dumps(entry_points, indent=2),
        "pyproject.toml": "[project]\nrequires-python = '>=3.11'\ndependencies = []\n",
        "main.py": "def main():\n    return 123\n",
        "alt.py": "def run():\n    return 456\n",
    }


def test_valid_bvpackage_passes(tmp_path: Path) -> None:
    pkg = tmp_path / "demo_pkg-0.0.1.bvpackage"
    _write_zip(pkg, _valid_files())

    result = validate_bvpackage_contract_v1(str(pkg))

    assert result.name == "demo_pkg"
    assert result.version == "0.0.1"
    assert result.default_entrypoint_name == "main"


def test_missing_bvproject_yaml_fails(tmp_path: Path) -> None:
    pkg = tmp_path / "demo_pkg-0.0.1.bvpackage"
    files = _valid_files()
    files.pop("bvproject.yaml")
    _write_zip(pkg, files)

    with pytest.raises(BVPackageContractError) as e:
        validate_bvpackage_contract_v1(str(pkg))

    assert "Missing required files" in str(e.value)


def test_multiple_default_entrypoints_fails(tmp_path: Path) -> None:
    pkg = tmp_path / "demo_pkg-0.0.1.bvpackage"
    _write_zip(pkg, _valid_files(multiple_defaults=True))

    with pytest.raises(BVPackageContractError) as e:
        validate_bvpackage_contract_v1(str(pkg))

    msg = str(e.value)
    assert "exactly one entrypoint" in msg
    assert "default: true" in msg


def test_invalid_semver_fails(tmp_path: Path) -> None:
    pkg = tmp_path / "demo_pkg-notsemver.bvpackage"
    _write_zip(pkg, _valid_files(version="1"))

    with pytest.raises(BVPackageContractError) as e:
        validate_bvpackage_contract_v1(str(pkg))

    assert "must be SemVer" in str(e.value)


def test_entry_points_json_mismatch_fails(tmp_path: Path) -> None:
    pkg = tmp_path / "demo_pkg-0.0.1.bvpackage"
    files = _valid_files()

    bad = json.loads(files["entry-points.json"])
    bad["entryPoints"][0]["function"] = "not_main"
    files["entry-points.json"] = json.dumps(bad, indent=2)

    _write_zip(pkg, files)

    with pytest.raises(BVPackageContractError) as e:
        validate_bvpackage_contract_v1(str(pkg))

    assert "does not match bvproject.yaml command" in str(e.value)


def test_reupload_same_name_version_rejected(tmp_path: Path) -> None:
    pkg = tmp_path / "demo_pkg-0.0.1.bvpackage"
    _write_zip(pkg, _valid_files())

    result = validate_bvpackage_contract_v1(str(pkg))

    registry: set[tuple[str, str]] = set()
    reject_reupload(result.identity, registry)
    registry.add(result.identity)

    with pytest.raises(BVPackageContractError) as e:
        reject_reupload(result.identity, registry)

    assert "Re-upload rejected" in str(e.value)
