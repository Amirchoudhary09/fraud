"""Role -> permission matrix. Every endpoint checks a permission server-side; the frontend
only uses /api/auth/me permissions to hide buttons.

Case content is additionally protected by case-level access (case_members), see
services/access.py: a role permission alone does not open another user's case.
"""

ROLES = ("super_admin", "security_admin", "investigator", "analyst", "auditor", "user")

_ALL_WORK = {"search.create", "search.view_own", "feedback.submit", "report.view"}

PERMISSIONS: dict[str, set[str]] = {
    "user": {"search.create", "search.view_own", "report.view"},
    "analyst": _ALL_WORK | {"case.create", "incident.create", "evidence.capture"},
    "investigator": _ALL_WORK | {"case.create", "incident.create", "evidence.capture", "evidence.export",
                                 "case.share", "audit.view_case"},
    "auditor": {"audit.view", "audit.verify", "security.view", "search.view_own"},
    "security_admin": {"users.manage", "audit.view", "audit.verify", "security.view", "security.manage",
                       "break_glass.approve", "search.view_own"},
    "super_admin": _ALL_WORK | {"case.create", "incident.create", "evidence.capture", "evidence.export",
                                "case.share", "audit.view_case", "audit.view", "audit.verify", "security.view",
                                "security.manage", "users.manage", "break_glass.approve", "search.view_all",
                                "case.view_all", "data.delete", "admin.evaluate"},
}

# Nobody holds these: the audit log cannot be edited or deleted through the application.
FORBIDDEN_FOR_ALL = {"audit.delete", "audit.modify"}


def has(role: str, permission: str) -> bool:
    return permission not in FORBIDDEN_FOR_ALL and permission in PERMISSIONS.get(role, set())


def of(role: str) -> list[str]:
    return sorted(PERMISSIONS.get(role, set()))
