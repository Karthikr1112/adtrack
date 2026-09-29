from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.http import Http404

from accounts.decorators import role_required
from accounts.permissions import reviewable_stages, can_edit_record, is_personal_view
from banners import workflow as proposal_workflow
from .models import PaymentClaim
from .forms import PaymentClaimForm
from . import workflow


def _detail_queryset():
    return PaymentClaim.objects.select_related(
        'created_by', 'work_order', 'work_order__proposal', 'work_order__proposal__campaign',
        'work_order__proposal__vendor', 'work_order__proposal__category', 'current_step__role',
    )


@role_required('can_add_payment')
def payment_upload(request):
    """Payments Upload page — submit bill/work order/proof/covering letter
    against an approved Work Order. Same submit-for-approval flow as
    adding a Proposal."""
    if request.method == 'POST':
        form = PaymentClaimForm(request.POST, request.FILES)
        if form.is_valid():
            claim = form.save(commit=False)
            claim.created_by = request.user
            claim.save()
            workflow.submit(claim, request.user)
            proposal_workflow.invalidate_pending_counts_for_step(claim.current_step)
            messages.success(request, f'Payment {claim.payment_number} submitted for approval.')
            return redirect('payment_detail', pk=claim.pk)
    else:
        form = PaymentClaimForm()

    return render(request, 'payments/payment_upload.html', {
        'form': form,
        'next_payment_number': PaymentClaim.next_payment_number_preview(),
    })


@role_required('can_view_payments')
def payment_list(request):
    """Payments Records page — every payment claim submitted so far.

    Same ownership rule as the Dashboard/Proposals list: a plain
    Executive only sees payments they created themselves; anyone with
    broader responsibility (reviewer/admin/superuser) sees every payment,
    org-wide."""
    claims = _detail_queryset().order_by('-created_at')
    if is_personal_view(request.user):
        claims = claims.filter(created_by=request.user)
    page_obj = Paginator(claims, 25).get_page(request.GET.get('page'))
    return render(request, 'payments/payment_list.html', {'claims': page_obj, 'page_obj': page_obj})


@role_required('can_edit_payment')
def payment_edit(request, pk):
    claim = get_object_or_404(PaymentClaim, pk=pk)
    if not can_edit_record(request.user, claim):
        raise PermissionDenied(
            "You can only edit payments you created, and only before they're approved."
        )
    needs_rework = claim.approval_status == 'rework'

    if request.method == 'POST':
        form = PaymentClaimForm(request.POST, request.FILES, instance=claim)
        if form.is_valid():
            form.save()
            if needs_rework:
                # Editing a reworked claim resubmits it — back to the
                # first approval step.
                workflow.resubmit(claim, request.user)
                proposal_workflow.invalidate_pending_counts_for_step(claim.current_step)
                messages.success(request, f'Payment {claim.payment_number} resubmitted for approval.')
            else:
                messages.success(request, 'Payment updated successfully.')
            return redirect('payment_detail', pk=claim.pk)
        messages.error(request, 'Please correct the errors below.')
    else:
        form = PaymentClaimForm(instance=claim)

    # (field name, bound field, currently-stored file or None) for each
    # upload — lets the edit template show a download link for what's
    # already uploaded, next to the "replace it" file input.
    documents = [
        (name, form[name], getattr(claim, name) if getattr(claim, name) else None)
        for name in ('bill_file', 'work_order_file', 'proof_file', 'covering_letter_file')
    ]

    return render(request, 'payments/payment_edit.html', {
        'form': form,
        'claim': claim,
        'documents': documents,
        'needs_rework': needs_rework,
        'rework_note': claim.approval_history.filter(action='rework').order_by('-created_at').first() if needs_rework else None,
    })


@role_required('can_delete_payment')
def payment_delete(request, pk):
    claim = get_object_or_404(_detail_queryset(), pk=pk)
    if request.method == 'POST':
        claim.delete()
        messages.success(request, 'Payment claim deleted successfully.')
        return redirect('payment_list')
    return render(request, 'payments/payment_confirm_delete.html', {'claim': claim})


@role_required('can_view_payments')
def payment_detail(request, pk):
    claim = get_object_or_404(_detail_queryset(), pk=pk)
    return render(request, 'payments/payment_detail.html', {
        'claim': claim,
        'history': claim.approval_history.select_related('actor').all(),
        'my_review_stages': reviewable_stages(request.user),
    })


@login_required
def payment_approvals(request):
    """Shared review queue: every payment claim currently sitting at any
    step this user is permitted to act on."""
    from accounts.permissions import can_review_anything
    if not can_review_anything(request.user):
        raise PermissionDenied("You don't have permission to review payments.")

    steps = reviewable_stages(request.user)
    if request.user.is_superuser:
        claims = PaymentClaim.objects.filter(approval_status='in_review')
    elif steps:
        claims = PaymentClaim.objects.filter(
            approval_status='in_review',
            current_step_id__in=steps,
        )
    else:
        claims = PaymentClaim.objects.none()

    claims = claims.select_related(
        'created_by', 'work_order', 'work_order__proposal', 'work_order__proposal__campaign', 'current_step__role'
    ).order_by('current_step__order', '-created_at')
    page_obj = Paginator(claims, 25).get_page(request.GET.get('page'))
    return render(request, 'payments/payment_approvals.html', {'claims': page_obj, 'page_obj': page_obj})


@login_required
def payment_review(request, pk):
    """The summary-before-approval screen for a payment claim - full
    details, complete approval history, and step-appropriate action
    buttons with a comment box. Same layout as proposal_review."""
    claim = get_object_or_404(_detail_queryset(), pk=pk)
    step = claim.current_step
    my_steps = reviewable_stages(request.user)

    can_act = (step is not None) and ((step.id in my_steps) or request.user.is_superuser)
    can_rework = bool(step) and step.allow_rework
    can_reject = bool(step) and getattr(step, 'can_reject', step.order > 2)
    has_next_step = bool(step) and proposal_workflow.next_step(step) is not None
    is_first_step = bool(step) and proposal_workflow.previous_step(step) is None
    is_next_level = bool(step) and step.order in (1, 2)
    is_level_3 = bool(step) and step.order == 3
    is_final_step = bool(step) and (step.order > 3 or proposal_workflow.next_step(step) is None)

    return render(request, 'payments/payment_review.html', {
        'claim': claim,
        'history': claim.approval_history.select_related('actor').all(),
        'can_act': can_act,
        'can_rework': can_rework,
        'can_reject': can_reject,
        'stage_label': claim.stage_label,
        'is_first_step': is_first_step,
        'has_next_step': has_next_step,
        'is_next_level': is_next_level,
        'is_level_3': is_level_3,
        'is_final_step': is_final_step,
    })


@login_required
def payment_approve_action(request, pk, action):
    if action not in ('approve', 'reject', 'rework'):
        raise Http404
    claim = get_object_or_404(PaymentClaim.objects.select_related('current_step__role'), pk=pk)
    step = claim.current_step

    if step is None:
        raise PermissionDenied("This payment is not currently in review.")

    if step.id not in reviewable_stages(request.user) and not request.user.is_superuser:
        raise PermissionDenied("You don't have permission to act on this payment at its current stage.")

    if request.method == 'POST':
        comment = request.POST.get('comment', '').strip()
        if not comment:
            messages.error(request, 'A comment is required for every decision.')
            return redirect('payment_review', pk=claim.pk)
        if action == 'rework' and not step.allow_rework:
            raise PermissionDenied("This stage has no rework option.")
        if action == 'reject' and not getattr(step, 'can_reject', step.order > 2):
            raise PermissionDenied("Step 1 and Step 2 do not have a reject option.")

        workflow.apply_action(claim, step, action, request.user, comment=comment)

        if action == 'approve':
            if step.order in (1, 2):
                upcoming = claim.current_step
                verb = f'sent to the next level ({upcoming.role.name} review)' if upcoming else 'sent to the next level'
            elif step.order == 3:
                upcoming = claim.current_step
                verb = f'approved and sent to {upcoming.role.name} review' if upcoming else 'fully approved'
            else:
                verb = 'fully approved'
        else:
            verb = {'reject': 'rejected', 'rework': 'sent for rework'}[action]
        messages.success(request, f'Payment {claim.payment_number} {verb}.')

        proposal_workflow.invalidate_pending_counts_for_step(step)
        proposal_workflow.invalidate_pending_counts_for_step(claim.current_step)
    return redirect('payment_approvals')
