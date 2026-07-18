from django.contrib import admin
from .models import Profile, Role, Feature

@admin.register(Feature)
class FeatureAdmin(admin.ModelAdmin):
    list_display = ('name', 'codename', 'category')
    search_fields = ('name', 'codename', 'category')

@admin.register(Role)
class RoleAdmin(admin.ModelAdmin):
    list_display = ('name',)
    search_fields = ('name',)
    filter_horizontal = ('permissions',)

@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'role', 'department', 'phone_number')
    list_filter = ('role',)
    search_fields = ('user__username', 'user__email')
