# Converts permissions from the Feature table + M2M into boolean columns on
# Role. Existing matrix ticks are copied over, then the old table is dropped.
from django.db import migrations, models

CODENAMES = [
    'can_view_dashboard', 'can_view_banners', 'can_add_banner',
    'can_edit_banner', 'can_delete_banner', 'can_add_placement',
    'can_upload_photo', 'can_add_cost', 'can_manage_users',
    'can_approve_requests', 'can_manage_roles',
]


def copy_m2m_to_columns(apps, schema_editor):
    Role = apps.get_model('accounts', 'Role')
    for role in Role.objects.all():
        granted = set(role.permissions.values_list('codename', flat=True))
        for codename in CODENAMES:
            setattr(role, codename, codename in granted)
        role.save()


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0007_seed_features_and_roles'),
    ]

    operations = [
        *[
            migrations.AddField(
                model_name='role',
                name=codename,
                field=models.BooleanField(default=False),
            )
            for codename in CODENAMES
        ],
        migrations.RunPython(copy_m2m_to_columns, migrations.RunPython.noop),
        migrations.RemoveField(model_name='role', name='permissions'),
        migrations.DeleteModel(name='Feature'),
    ]
