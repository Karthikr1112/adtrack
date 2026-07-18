from django.contrib import admin

from .models import Profile, Role


@admin.register(Role)
class RoleAdmin(admin.ModelAdmin):
    list_display = ('name', 'granted')
    search_fields = ('name',)

    def get_fields(self, request, obj=None):
        # name first, then the permission columns read from the model
        return ['name'] + Role.permission_fields()

    @admin.display(description='Permissions granted')
    def granted(self, obj):
        labels = [Role.permission_label(c) for c in sorted(obj.permission_codenames())]
        return ', '.join(labels) if labels else '—'


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'role', 'department', 'phone_number')
    list_filter = ('role',)
    search_fields = ('user__username', 'user__email')
