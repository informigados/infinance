from __future__ import annotations

ROLE_CAPABILITIES: dict[str, set[str]] = {
    'admin': {'read', 'write', 'admin'},
    'operator': {'read', 'write'},
    'viewer': {'read'},
}

VALID_ROLES = tuple(ROLE_CAPABILITIES.keys())


def has_permission(role: str | None, permission: str) -> bool:
    if not role:
        return False
    return permission in ROLE_CAPABILITIES.get(role, set())
