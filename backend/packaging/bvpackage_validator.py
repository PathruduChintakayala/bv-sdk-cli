"""Compatibility wrapper.

Phase A deliverable path: backend/packaging/bvpackage_validator.py

Implementation lives in src/bv/packaging/bvpackage_validator.py so it can be reused.
"""

from bv.packaging.bvpackage_validator import (  # noqa: F401
    BVPackageContractError,
    BVPackageContractV1Result,
    BVPackageEntrypoint,
    is_bvpackage_path,
    reject_reupload,
    validate_bvpackage_contract_v1,
)
