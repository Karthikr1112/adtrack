# Converts existing PaymentClaim rows from the old hardcoded stage
# vocabulary ('coordinator'/'head'/'ceo'/'executive_rework') to the new
# configurable-WorkflowStep scheme. (The shared ApprovalAction rows for
# payment claims were already converted by banners.0021, since that
# migration loops over every ApprovalAction regardless of which document
# type it belongs to.)

from django.db import migrations


def convert_legacy_data(apps, schema_editor):
    PaymentClaim = apps.get_model('payments', 'PaymentClaim')
    WorkflowStep = apps.get_model('accounts', 'WorkflowStep')

    steps_by_order = {s.order: s for s in WorkflowStep.objects.all()}
    STAGE_TO_ORDER = {'coordinator': 1, 'head': 2, 'ceo': 3}

    for claim in PaymentClaim.objects.all():
        old_value = claim.approval_status
        if old_value in STAGE_TO_ORDER:
            step = steps_by_order.get(STAGE_TO_ORDER[old_value])
            claim.current_step = step
            claim.approval_status = 'in_review'
            claim.save(update_fields=['current_step', 'approval_status'])
        elif old_value == 'executive_rework':
            claim.approval_status = 'rework'
            claim.save(update_fields=['approval_status'])


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0013_remove_role_can_review_as_ceo_and_more'),
        ('payments', '0003_paymentclaim_current_step_and_more'),
        ('banners', '0021_convert_legacy_approval_data'),
    ]

    operations = [
        migrations.RunPython(convert_legacy_data, migrations.RunPython.noop),
    ]
