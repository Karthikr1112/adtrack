"""Per-request permission helpers.

A user's role permissions are loaded once per request and cached on the
user object, so the navbar, list-row buttons, decorators, and views all
share a single query instead of one query per check.
"""

_CACHE_ATTR = '_role_perm_codenames'


def get_role_permissions(user):
    """Returns the frozenset of permission codenames for the user's role,
    cached on the user instance for the lifetime of the request."""
    perms = getattr(user, _CACHE_ATTR, None)
    if perms is None:
        profile = getattr(user, 'profile', None)
        if profile is None or profile.role is None:
            perms = frozenset()
        else:
            perms = frozenset(profile.role.permissions.values_list('codename', flat=True))
        setattr(user, _CACHE_ATTR, perms)
    return perms


def user_has_permission(user, codename):
    """True if the user is a superuser or their role grants the codename."""
    if not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    return codename in get_role_permissions(user)
