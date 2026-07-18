from django.db import models
from django.contrib.auth.models import User

class Feature(models.Model):
    name = models.CharField(max_length=100, db_index=True)
    codename = models.CharField(max_length=50, unique=True)
    category = models.CharField(max_length=50, default='General', db_index=True)

    def __str__(self):
        return f"{self.name} ({self.codename})"

class Role(models.Model):
    name = models.CharField(max_length=50, unique=True)
    permissions = models.ManyToManyField(Feature, blank=True, related_name='roles')

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
        if not self.role: return False
        return self.role.permissions.filter(codename='can_manage_users').exists()

    @property
    def is_manager(self):
        if not self.role: return False
        return self.role.permissions.filter(codename__in=['can_manage_users', 'can_view_dashboard']).exists()