# Renames the Banner model/table to Proposal (RenameModel updates the actual
# DB table name — banners_banner -> banners_proposal — and keeps every FK
# relation intact automatically, no data loss) and adds the system-generated
# proposal_number ("PRO-MKT-0001", assigned in Proposal.save()).
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('banners', '0007_campaign_category_subcategory_and_more'),
    ]

    operations = [
        migrations.RenameModel(old_name='Banner', new_name='Proposal'),
        migrations.AddField(
            model_name='proposal',
            name='proposal_number',
            field=models.CharField(blank=True, editable=False, max_length=20, null=True, unique=True),
        ),
    ]
