"""The permission matrix: ONE constant mapping capability -> roles allowed. docs/data_contract.md must agree
(a test parses the document and compares). Routers use ``deps.require_capability(name)``; nothing else decides roles.
"""
from __future__ import annotations

ADMINISTRATOR = "administrator"
CLINICAL_OPS = "clinical_ops"
ANALYST = "analyst"
ALL_ROLES = frozenset({ADMINISTRATOR, CLINICAL_OPS, ANALYST})

PERMISSIONS: dict[str, frozenset[str]] = {
    "dashboards": ALL_ROLES,                                   # dashboards and analytics endpoints
    "export_aggregated": ALL_ROLES,                            # export aggregated reports
    "list_encounters": ALL_ROLES,                              # list and search encounters (analyst: minimised)
    "export_encounters": frozenset({ADMINISTRATOR, CLINICAL_OPS}),  # export encounter-level data
    "view_patients": frozenset({ADMINISTRATOR, CLINICAL_OPS}),      # view patient records (race, gender)
    "write_records": frozenset({ADMINISTRATOR, CLINICAL_OPS}),      # create and update patients and encounters
    "delete_records": frozenset({ADMINISTRATOR}),                   # soft delete patients and encounters
    "view_pipeline": frozenset({ADMINISTRATOR, CLINICAL_OPS}),      # pipeline runs and data-quality issues (read)
    "view_audit": frozenset({ADMINISTRATOR}),                       # audit logs
    "manage_users": frozenset({ADMINISTRATOR}),                     # user management
}

# Capabilities where a role may call the endpoint but receives a data-minimised response.
MINIMISED: dict[str, frozenset[str]] = {"list_encounters": frozenset({ANALYST})}


def roles_for(capability: str) -> frozenset[str]:
    """Roles allowed for a capability (KeyError for an unknown capability so typos fail loudly)."""
    return PERMISSIONS[capability]


def is_minimised(capability: str, role: str) -> bool:
    """True when ``role`` gets the data-minimised variant of ``capability``."""
    return role in MINIMISED.get(capability, frozenset())
