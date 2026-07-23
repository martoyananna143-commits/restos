"""Access profile model package."""

from app.infra.database.models.access_profile.access_profile import (
    AccessProfile,
    AccessProfilePermission,
)

__all__ = ["AccessProfile", "AccessProfilePermission"]
