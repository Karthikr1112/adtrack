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


_STAGES_CACHE_ATTR = '_reviewable_stages_cache'
_CAN_REVIEW_CACHE_ATTR = '_can_review_anything_cache'


def reviewable_stages(user):
    """The set of WorkflowStep ids this user is allowed to act on — a step
    matches if the user's role is the one assigned to it on the Approval
    Flow page AND the role has can_approve_banners enabled in the Role Matrix.
    Superusers can act on every configured step."""
    if not user.is_authenticated:
        return frozenset()
    stages = getattr(user, _STAGES_CACHE_ATTR, None)
    if stages is not None:
        return stages

    from .models import WorkflowStep
    if user.is_superuser:
        stages = frozenset(WorkflowStep.objects.values_list('id', flat=True))
    else:
        profile = getattr(user, 'profile', None)
        if profile is None or profile.role_id is None:
            stages = frozenset()
        elif not profile.role.can_approve_banners:
            stages = frozenset()
        else:
            stages = frozenset(WorkflowStep.objects.filter(role_id=profile.role_id).values_list('id', flat=True))
    setattr(user, _STAGES_CACHE_ATTR, stages)
    return stages


def can_review_anything(user):
    """True if the user's role has can_approve_banners checked, or is assigned
    to at least one configured approval step, or is assigned as a
    final approver, or is a superuser. This determines visibility of the
    Proposal Approvals and Payment Approvals nav links and pages."""
    if not user.is_authenticated:
        return False
    val = getattr(user, _CAN_REVIEW_CACHE_ATTR, None)
    if val is not None:
        return val

    if user.is_superuser:
        val = True
    elif user_has_permission(user, 'can_approve_banners'):
        val = True
    elif bool(reviewable_stages(user)):
        val = True
    else:
        from banners.models import Proposal
        val = Proposal.objects.filter(final_approver=user).exists()
    setattr(user, _CAN_REVIEW_CACHE_ATTR, val)
    return val


def is_admin_user(user):
    """True for a superuser, or a user whose role has can_manage_users —
    this project's existing 'admin' concept (see Profile.is_admin).
    Admins get the same full-access bypass as superusers wherever
    ownership/approval-lock restrictions apply."""
    if not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    return user_has_permission(user, 'can_manage_users')


def is_personal_view(user):
    """True for a plain Executive — someone who can add proposals/payments
    but doesn't review anything, isn't an admin, and isn't a superuser.
    Such a user only sees their OWN documents; everyone with broader
    responsibility (a configured reviewer, an admin, or a superuser) sees
    every document, org-wide. Used consistently across the Dashboard, the
    Proposals list/export, and the Payments Records list, so a user's
    visibility doesn't silently differ from one page to the next."""
    return not (
        user.is_superuser
        or can_review_anything(user)
        or user_has_permission(user, 'can_manage_users')
    )


def can_edit_record(user, obj):
    """True if `user` may edit `obj` (a Proposal or PaymentClaim):
    - Superusers and admins (role has can_manage_users) can always edit
      anything, any status.
    - Everyone else may only edit records they created themselves.
    - Once a record's approval_status is 'approved', only a superuser/
      admin may edit it — the creator loses edit access at that point.
    Does NOT check the role's can_edit_banner/can_edit_payment flag —
    callers should still gate on that separately (e.g. via the
    `has_permission` filter/@role_required), this only adds the
    ownership + post-approval-lock rule on top."""
    if is_admin_user(user):
        return True
    if not user.is_authenticated:
        return False
    if obj.created_by_id != user.id:
        return False
    if obj.approval_status == 'approved':
        return False
    return True
