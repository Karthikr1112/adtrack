from django import template
from django.core.cache import cache

from accounts.permissions import user_has_permission

register = template.Library()

PENDING_COUNT_CACHE_KEY = 'pending_users_count'
PENDING_COUNT_CACHE_SECONDS = 30


@register.filter
def total_cost_sum(costs):
    """Sums the total_cost property across a prefetched list/queryset of BannerCost."""
    return sum((c.total_cost for c in costs), 0)


@register.filter
def has_permission(user, feature_name):
    """
    Check if a user's role has a specific permission.
    Usage: {% if user|has_permission:"can_add_banner" %}

    Backed by a per-request cache — all checks in a page share one query.
    """
    return user_has_permission(user, feature_name)


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
