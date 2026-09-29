"""PaymentClaim approval-chain logic.

Mirrors banners/workflow.py exactly — same configurable WorkflowStep
chain, same reviewer lookup, same rework/reject rules — but for
PaymentClaim instead of Proposal. The two document types are reviewed by
the identical, fully configurable Approval Flow, so the step-lookup
helpers are imported and reused rather than duplicated.
"""
from banners.models import ApprovalAction
from banners.workflow import first_step, next_step, previous_step, reviewers_for_step, oversight_users


def submit(claim, actor):
    """Creator submits a payment claim — it starts life awaiting the
    first configured step's review. Called once, right after the row is
    first saved."""
    step = first_step()
    if step is None:
        raise RuntimeError(
            'No approval flow is configured yet — add at least one step on the Approval Flow page.'
        )
    claim.current_step = step
    claim.approval_status = 'in_review'
    claim.save(update_fields=['current_step', 'approval_status'])
    ApprovalAction.objects.create(payment_claim=claim, stage='Executive', action='submitted', actor=actor)


def resubmit(claim, actor):
    """Creator resubmits a claim that was sent back for rework — moves
    back to the first step."""
    step = first_step()
    claim.current_step = step
    claim.approval_status = 'in_review'
    claim.save(update_fields=['current_step', 'approval_status'])
    ApprovalAction.objects.create(payment_claim=claim, stage='Executive', action='resubmitted', actor=actor)


def apply_action(claim, step, action, actor, comment=''):
    """Applies a reviewer's decision. `step` is the WorkflowStep the
    claim was at when the decision was made (the view must have already
    confirmed this matches claim.current_step and that `actor`'s role
    matches it before calling this)."""
    ApprovalAction.objects.create(
        payment_claim=claim, stage=step.role.name, workflow_step=step, action=action, actor=actor, comment=comment,
    )

    if action == 'approve':
        upcoming = next_step(step)
        if upcoming is None or (claim.final_approver and step.order >= 4):
            claim.approval_status = 'approved'
            claim.current_step = None
            claim.save(update_fields=['approval_status', 'current_step'])
        else:
            claim.current_step = upcoming
            claim.save(update_fields=['current_step'])

    elif action == 'reject':
        if step.order in (1, 2) or not getattr(step, 'can_reject', getattr(step, 'allow_reject', True)):
            raise ValueError(f'{step} has no reject option')
        claim.approval_status = 'rejected'
        claim.current_step = None
        claim.save(update_fields=['approval_status', 'current_step'])

    elif action == 'rework':
        if not step.allow_rework:
            raise ValueError(f'{step} has no rework option')
        target = previous_step(step)
        if target is None:
            claim.approval_status = 'rework'
            claim.current_step = None
            claim.save(update_fields=['approval_status', 'current_step'])
        else:
            claim.current_step = target
            claim.approval_status = 'in_review'
            claim.save(update_fields=['current_step', 'approval_status'])
    else:
        raise ValueError(f'Unknown action {action!r}')
