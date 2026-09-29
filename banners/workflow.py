"""Proposal approval-chain logic.

The chain itself — how many steps there are, and which Role reviews at
each one — is fully configurable via accounts.WorkflowStep (managed from
the Approval Flow page). Nothing about a specific role's name is
hardcoded here; this module only ever deals with WorkflowStep objects in
`order`.
"""
from django.contrib.auth.models import User
from django.db.models import Q

from accounts.models import WorkflowStep
from .models import ApprovalAction, WorkOrder


def ordered_steps():
    """Every configured step, in order — the current Approval Flow."""
    return list(WorkflowStep.objects.select_related('role').order_by('order'))


def first_step():
    """The step a freshly-submitted document starts at, or None if no
    Approval Flow has been configured yet."""
    return WorkflowStep.objects.select_related('role').order_by('order').first()


def next_step(step):
    """The step after `step`, or None if `step` is the last one (meaning
    the document is now fully approved)."""
    steps = ordered_steps()
    idx = next((i for i, s in enumerate(steps) if s.id == step.id), None)
    if idx is None or idx + 1 >= len(steps):
        return None
    return steps[idx + 1]


def previous_step(step):
    """The step before `step`, or None if `step` is the first one (meaning
    a rework here goes all the way back to the creator)."""
    steps = ordered_steps()
    idx = next((i for i, s in enumerate(steps) if s.id == step.id), None)
    if not idx:
        return None
    return steps[idx - 1]


def reviewers_for_step(step):
    """Every user whose role matches this step."""
    return User.objects.filter(profile__role_id=step.role_id).distinct()


def oversight_users():
    """Reviewers at every step EXCEPT the first, plus superusers, see
    every action on every document — not just the ones at their own step
    — for full pipeline visibility. (The first-line reviewer only sees
    their own queue.) Reused by payments.workflow."""
    steps = ordered_steps()
    later_role_ids = [s.role_id for s in steps[1:]]
    return User.objects.filter(
        Q(profile__role_id__in=later_role_ids) | Q(is_superuser=True)
    ).distinct()


def invalidate_pending_counts_for_step(step, user_id=None):
    """Clears the cached 'pending approvals' sidebar badge for every
    reviewer of `step`, and optionally for a specific `user_id` (e.g. assigned final approver)."""
    from django.core.cache import cache
    if step is not None:
        for user in reviewers_for_step(step):
            cache.delete(f'pending_banners_count_{user.id}')
            cache.delete(f'pending_payments_count_{user.id}')
    if user_id is not None:
        cache.delete(f'pending_banners_count_{user_id}')
        cache.delete(f'pending_payments_count_{user_id}')


def submit(proposal, actor):
    """Executive creates a proposal — it starts life awaiting the first
    configured step's review. Called once, right after the Proposal row
    is first saved."""
    step = first_step()
    if step is None:
        raise RuntimeError(
            'No approval flow is configured yet — add at least one step on the Approval Flow page.'
        )
    proposal.current_step = step
    proposal.approval_status = 'in_review'
    proposal.save(update_fields=['current_step', 'approval_status'])
    ApprovalAction.objects.create(proposal=proposal, stage='Executive', action='submitted', actor=actor)


def resubmit(proposal, actor):
    """Executive edits a proposal that was sent back for rework and
    resubmits it — moves back to the first step."""
    step = first_step()
    proposal.current_step = step
    proposal.approval_status = 'in_review'
    proposal.save(update_fields=['current_step', 'approval_status'])
    ApprovalAction.objects.create(proposal=proposal, stage='Executive', action='resubmitted', actor=actor)


def apply_action(proposal, step, action, actor, comment='', attachment=None):
    """Applies a reviewer's decision. If proposal.awaiting_final_approver is True,
    this is the assigned final approver making the final decision. Otherwise,
    `step` is the WorkflowStep the proposal was at."""
    stage_name = 'Final Approval' if proposal.awaiting_final_approver else (step.role.name if step else 'Final Approval')
    ApprovalAction.objects.create(
        proposal=proposal, stage=stage_name, workflow_step=step, action=action, actor=actor,
        comment=comment, attachment=attachment,
    )

    if action == 'approve':
        if proposal.awaiting_final_approver:
            # Final approver approved -> Work order is generated!
            proposal.approval_status = 'approved'
            proposal.current_step = None
            proposal.awaiting_final_approver = False
            proposal.save(update_fields=['approval_status', 'current_step', 'awaiting_final_approver'])
            WorkOrder.objects.get_or_create(proposal=proposal)
        else:
            upcoming = next_step(step)
            if upcoming is None:
                # End of configured steps (e.g. Step 4 CEO)
                if proposal.final_approver:
                    # Move to the assigned final approver
                    proposal.awaiting_final_approver = True
                    proposal.approval_status = 'in_review'
                    proposal.save(update_fields=['awaiting_final_approver', 'approval_status'])
                else:
                    # Normal flow: fully approved and Work Order generated
                    proposal.approval_status = 'approved'
                    proposal.current_step = None
                    proposal.awaiting_final_approver = False
                    proposal.save(update_fields=['approval_status', 'current_step', 'awaiting_final_approver'])
                    WorkOrder.objects.get_or_create(proposal=proposal)
            else:
                proposal.current_step = upcoming
                proposal.save(update_fields=['current_step'])

    elif action == 'reject':
        if not proposal.awaiting_final_approver and (step.order in (1, 2) or not getattr(step, 'can_reject', getattr(step, 'allow_reject', True))):
            raise ValueError(f'{step} has no reject option')
        proposal.approval_status = 'rejected'
        proposal.current_step = None
        proposal.awaiting_final_approver = False
        proposal.save(update_fields=['approval_status', 'current_step', 'awaiting_final_approver'])

    elif action == 'rework':
        if proposal.awaiting_final_approver:
            # Final approver requests rework: send back to CEO (step 4)
            proposal.awaiting_final_approver = False
            proposal.approval_status = 'in_review'
            proposal.save(update_fields=['awaiting_final_approver', 'approval_status'])
        else:
            if not step.allow_rework:
                raise ValueError(f'{step} has no rework option')
            target = previous_step(step)
            if target is None:
                # First step's rework: back to the creator to edit & resubmit.
                proposal.approval_status = 'rework'
                proposal.current_step = None
                proposal.save(update_fields=['approval_status', 'current_step'])
            else:
                proposal.current_step = target
                proposal.approval_status = 'in_review'
                proposal.save(update_fields=['current_step', 'approval_status'])
    else:
        raise ValueError(f'Unknown action {action!r}')
