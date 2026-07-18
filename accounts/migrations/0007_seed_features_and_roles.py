# One-time seed of the app's permission Features and default Roles, so a
# fresh database is usable immediately. Uses get_or_create everywhere, so
# it is safe on databases that already have data.
from django.db import migrations

FEATURES = [
    # (name, codename, category)
    ('View Dashboard', 'can_view_dashboard', 'Dashboard'),
    ('View Banners', 'can_view_banners', 'Banners'),
    ('Add Banner', 'can_add_banner', 'Banners'),
    ('Edit Banner', 'can_edit_banner', 'Banners'),
    ('Delete Banner', 'can_delete_banner', 'Banners'),
    ('Add Placement', 'can_add_placement', 'Banners'),
    ('Upload Photo', 'can_upload_photo', 'Banners'),
    ('Add Cost', 'can_add_cost', 'Banners'),
    ('Manage Users', 'can_manage_users', 'Administration'),
    ('Approve Requests', 'can_approve_requests', 'Administration'),
    ('Manage Roles', 'can_manage_roles', 'Administration'),
]

ROLES = {
    # role name -> feature codenames
    'Admin': [codename for _, codename, _ in FEATURES],
    'Manager': [
        'can_view_dashboard', 'can_view_banners', 'can_add_banner',
        'can_edit_banner', 'can_add_placement', 'can_upload_photo',
        'can_add_cost',
    ],
    'Field Staff': [
        'can_view_banners', 'can_add_placement', 'can_upload_photo',
    ],
}


def seed(apps, schema_editor):
    Feature = apps.get_model('accounts', 'Feature')
    Role = apps.get_model('accounts', 'Role')

    features_by_codename = {}
    for name, codename, category in FEATURES:
        feature, _ = Feature.objects.get_or_create(
            codename=codename,
            defaults={'name': name, 'category': category},
        )
        features_by_codename[codename] = feature

    for role_name, codenames in ROLES.items():
        role, created = Role.objects.get_or_create(name=role_name)
        if created:
            # Only preset permissions for roles this migration itself created —
            # never overwrite an admin's existing matrix choices.
            role.permissions.set([features_by_codename[c] for c in codenames])


def unseed(apps, schema_editor):
    # Intentionally a no-op: removing features/roles on rollback could
    # destroy role assignments an admin has since customized.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0006_remove_profile_is_deactivated'),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]
