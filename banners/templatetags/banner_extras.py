import os

from django import template
from django.core.cache import cache
from django.templatetags.static import static
from django.conf import settings

from accounts.permissions import user_has_permission, reviewable_stages, can_review_anything, can_edit_record

register = template.Library()

PENDING_COUNT_CACHE_KEY = 'pending_users_count'
PENDING_BANNERS_CACHE_KEY = 'pending_banners_count'  # per-user, see below
PENDING_COUNT_CACHE_SECONDS = 30


@register.filter
def stage_display(stage):
    """ApprovalAction.stage is already stored as ready-to-display text
    (the reviewing role's name at the time, or 'Executive') — this filter
    is now just a passthrough, kept so existing |stage_display usages
    keep working unchanged."""
    return stage


@register.filter
def has_permission(user, feature_name):
    """
    Check if a user's role has a specific permission.
    Usage: {% if user|has_permission:"can_add_banner" %}

    Backed by a per-request cache — all checks in a page share one query.
    """
    return user_has_permission(user, feature_name)


@register.filter
def can_edit_proposal(banner, user):
    """True if the Edit button should show for this proposal + user:
    the role must have can_edit_banner AND the user must be allowed to
    edit this specific record (own proposal, not yet approved — unless
    they're a superuser, who can always edit).
    Usage: {% if banner|can_edit_proposal:user %}
    """
    return user_has_permission(user, 'can_edit_banner') and can_edit_record(user, banner)


@register.filter
def can_edit_payment(claim, user):
    """Same rule as can_edit_proposal, for Payment claims.
    Usage: {% if claim|can_edit_payment:user %}
    """
    return user_has_permission(user, 'can_edit_payment') and can_edit_record(user, claim)


@register.filter
def can_review(user):
    """True if user can review proposals."""
    return can_review_anything(user)


@register.filter
def can_review_proposals(user):
    """True if user can review proposals — includes assigned final approvers."""
    return can_review_anything(user)


@register.filter
def can_review_payments(user):
    """True if user can review payments — strictly requires an active workflow step role or superuser."""
    if not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    return bool(reviewable_stages(user))


@register.simple_tag
def get_pending_users_count():
    """Pending-approval badge in the navbar. Cached briefly so the query
    doesn't run on every single page render."""
    count = cache.get(PENDING_COUNT_CACHE_KEY)
    if count is None:
        from django.contrib.auth.models import User
        count = User.objects.filter(is_active=False).count()
        cache.set(PENDING_COUNT_CACHE_KEY, count, PENDING_COUNT_CACHE_SECONDS)
    return count


@register.simple_tag
def get_pending_banners_count(user):
    """Proposal-approvals badge — includes proposals assigned directly to user as final_approver."""
    if not user.is_authenticated:
        return 0
    cache_key = f'{PENDING_BANNERS_CACHE_KEY}_{user.id}'
    count = cache.get(cache_key)
    if count is None:
        from banners.models import Proposal
        from django.db.models import Q
        steps = reviewable_stages(user)
        if user.is_superuser:
            count = Proposal.objects.filter(approval_status='in_review').count()
        else:
            count = Proposal.objects.filter(
                approval_status='in_review'
            ).filter(
                Q(awaiting_final_approver=True, final_approver=user) |
                Q(awaiting_final_approver=False, current_step_id__in=steps)
            ).distinct().count()
        cache.set(cache_key, count, PENDING_COUNT_CACHE_SECONDS)
    return count


@register.simple_tag
def get_pending_payments_count(user):
    """Payment-approvals badge — respects reviewer roles."""
    if not user.is_authenticated:
        return 0
    cache_key = f'pending_payments_count_{user.id}'
    count = cache.get(cache_key)
    if count is None:
        from payments.models import PaymentClaim
        steps = reviewable_stages(user)
        if user.is_superuser:
            count = PaymentClaim.objects.filter(approval_status='in_review').count()
        elif steps:
            count = PaymentClaim.objects.filter(
                approval_status='in_review',
                current_step_id__in=steps
            ).count()
        else:
            count = 0
        cache.set(cache_key, count, PENDING_COUNT_CACHE_SECONDS)
    return count


@register.simple_tag
def versioned_static(path):
    """{% static %} plus "?v=<file mtime>" so a browser that already cached
    style.css picks up the new copy the moment it's edited, instead of
    needing a manual hard-refresh. Falls back to a plain static() URL if
    the source file can't be found on disk (e.g. collected to a different
    STATIC_ROOT in production without STATICFILES_DIRS access)."""
    url = static(path)
    for static_dir in getattr(settings, 'STATICFILES_DIRS', []):
        candidate = os.path.join(static_dir, path)
        if os.path.exists(candidate):
            return f'{url}?v={int(os.path.getmtime(candidate))}'
    return url
