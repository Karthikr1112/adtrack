from functools import wraps
from django.core.exceptions import PermissionDenied
from django.contrib.auth.decorators import login_required

from .permissions import user_has_permission


def role_required(feature_name):
    """
    @role_required('can_add_banner')
    def some_view(request):
        ...
    """
    def decorator(view_func):
        @wraps(view_func)
        @login_required
        def wrapper(request, *args, **kwargs):
            if not user_has_permission(request.user, feature_name):
                raise PermissionDenied("You don't have permission to perform this action.")
            return view_func(request, *args, **kwargs)
        return wrapper
    return decorator