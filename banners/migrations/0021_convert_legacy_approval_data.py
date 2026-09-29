# Converts existing Proposal/ApprovalAction rows from the old hardcoded
# stage vocabulary ('coordinator'/'head'/'ceo'/'executive_rework') to the
# new configurable-WorkflowStep scheme, using the steps seeded by
# accounts.0013 (which came straight from this data's own old
# can_review_as_* flags, so the mapping lines up exactly).

from django.db import migrations


def convert_legacy_data(apps, schema_editor):
    Proposal = apps.get_model('banners', 'Proposal')
    ApprovalAction = apps.get_model('banners', 'ApprovalAction')
    WorkflowStep = apps.get_model('accounts', 'WorkflowStep')

    steps_by_order = {s.order: s for s in WorkflowStep.objects.all()}
    # Old stage key -> step order, matching the seeding in accounts.0013.
    STAGE_TO_ORDER = {'coordinator': 1, 'head': 2, 'ceo': 3}

    for proposal in Proposal.objects.all():
        old_value = proposal.approval_status
        if old_value in STAGE_TO_ORDER:
            step = steps_by_order.get(STAGE_TO_ORDER[old_value])
            proposal.current_step = step
            proposal.approval_status = 'in_review'
            proposal.save(update_fields=['current_step', 'approval_status'])
        elif old_value == 'executive_rework':
            proposal.approval_status = 'rework'
            proposal.save(update_fields=['approval_status'])
        # 'approved' / 'rejected' already match the new vocabulary as-is.

    for action in ApprovalAction.objects.all():
        old_stage = action.stage
        if old_stage in STAGE_TO_ORDER:
            step = steps_by_order.get(STAGE_TO_ORDER[old_stage])
            if step is not None:
                action.workflow_step = step
                action.stage = step.role.name
                action.save(update_fields=['workflow_step', 'stage'])
        elif old_stage in ('executive', 'executive_rework'):
            action.stage = 'Executive'
            action.save(update_fields=['stage'])


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0013_remove_role_can_review_as_ceo_and_more'),
        ('banners', '0020_approvalaction_workflow_step_proposal_current_step_and_more'),
    ]

    operations = [
        migrations.RunPython(convert_legacy_data, migrations.RunPython.noop),
    ]
