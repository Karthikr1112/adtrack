from django.db import models
from django.contrib.auth.models import User


class Role(models.Model):
    """A role is one row; every permission is a BooleanField column below
    (tick = allowed). The Role Matrix page and the admin read these columns
    directly from the model — to add a new permission, just add one
    BooleanField starting with `can_` and run makemigrations + migrate."""

    name = models.CharField(max_length=50, unique=True)

    # Dashboard
    can_view_dashboard = models.BooleanField(default=False)
    # Banners
    can_view_banners = models.BooleanField(default=False)
    can_add_banner = models.BooleanField(default=False)
    can_edit_banner = models.BooleanField(default=False)
    can_delete_banner = models.BooleanField(default=False)
    can_add_placement = models.BooleanField(default=False)
    can_upload_photo = models.BooleanField(default=False)
    can_add_cost = models.BooleanField(default=False)
    # Administration
    can_manage_users = models.BooleanField(default=False)
    can_approve_requests = models.BooleanField(default=False)
    can_manage_roles = models.BooleanField(default=False)

    @classmethod
    def permission_fields(cls):
        """The permission column names, read directly from the model —
        every BooleanField whose name starts with `can_`."""
        return [
            f.name for f in cls._meta.get_fields()
            if isinstance(f, models.BooleanField) and f.name.startswith('can_')
        ]

    @staticmethod
    def permission_label(codename):
        """Auto label from the column name: can_view_dashboard -> 'View Dashboard'."""
        return codename.removeprefix('can_').replace('_', ' ').title()

    def permission_codenames(self):
        """Frozenset of granted permission column names — plain attribute
        reads, no extra query."""
        return frozenset(c for c in self.permission_fields() if getattr(self, c, False))

    def __str__(self):
        return self.name


class Profile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    role = models.ForeignKey('Role', on_delete=models.SET_NULL, null=True, blank=True)
    phone_number = models.CharField(max_length=15, blank=True, db_index=True)
    department = models.CharField(max_length=100, blank=True, db_index=True)

    def __str__(self):
        return f"{self.user.username} ({self.role.name if self.role else 'No Role'})"

    @property
    def is_admin(self):
        return bool(self.role and self.role.can_manage_users)

    @property
    def is_manager(self):
        return bool(self.role and (self.role.can_manage_users or self.role.can_view_dashboard))
