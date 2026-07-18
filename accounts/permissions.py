"""Per-request permission helpers.

Permissions are boolean columns on Role, so once the user's profile+role row
is loaded there are ZERO extra queries — checks are plain attribute reads.
The small per-user cache below avoids refetching profile/role repeatedly.
"""

_CACHE_ATTR = '_role_perm_codenames'


def get_role_permissions(user):
    """Returns the frozenset of granted permission codenames for the user's
    role, cached on the user instance for the lifetime of the request."""
    perms = getattr(user, _CACHE_ATTR, None)
    if perms is None:
        profile = getattr(user, 'profile', None)
        if profile is None or profile.role is None:
            perms = frozenset()
        else:
            perms = profile.role.permission_codenames()
        setattr(user, _CACHE_ATTR, perms)
    return perms


def user_has_permission(user, codename):
    """True if the user is a superuser or their role grants the codename."""
    if not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    return codename in get_role_permissions(user)
