from django.db import models, transaction
from django.contrib.auth.models import User

from banners.models import compress_image_field


class NumberSequence(models.Model):
    """A persistent, monotonically-increasing counter used to assign
    document numbers — deliberately NOT derived from any row's own primary
    key, so a number is never reused even if every record of that type is
    later deleted (unlike Proposal.proposal_number / WorkOrder.po_number,
    which read self.pk and can repeat on SQLite after a full table wipe).
    This is the industry-correct approach and is used here for
    PaymentClaim.payment_number."""

    key = models.CharField(max_length=50, unique=True)
    last_value = models.PositiveIntegerField(default=0)

    @classmethod
    def next_value(cls, key):
        with transaction.atomic():
            seq, _ = cls.objects.select_for_update().get_or_create(key=key, defaults={'last_value': 0})
            seq.last_value += 1
            seq.save(update_fields=['last_value'])
            return seq.last_value

    def __str__(self):
        return f'{self.key} = {self.last_value}'


class PaymentClaim(models.Model):
    """A payment request submitted against an already-approved Work Order —
    bill, work order copy, proof and covering letter uploads, reviewed by
    the exact same configurable Approval Flow as a Proposal (see
    accounts.WorkflowStep and payments.workflow)."""

    PAYMENT_NUMBER_PREFIX = 'PAY-MKT-'

    # Same vocabulary as Proposal.approval_status, reused so the existing
    # review-queue/permission logic (reviewable_stages, etc.) applies
    # unchanged to payments too.
    APPROVAL_CHOICES = [
        ('rework', 'Needs Rework'),
        ('in_review', 'In Review'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    ]

    work_order = models.ForeignKey(
        'banners.WorkOrder', related_name='payment_claims', on_delete=models.PROTECT,
        help_text='The Work Order this payment is being claimed against.',
    )
    payment_number = models.CharField(max_length=30, unique=True, null=True, blank=True, editable=False)

    bill_file = models.FileField(upload_to='payments/bills/%Y/%m/')
    work_order_file = models.FileField(upload_to='payments/work_orders/%Y/%m/')
    proof_file = models.FileField(upload_to='payments/proofs/%Y/%m/')
    covering_letter_file = models.FileField(upload_to='payments/covering_letters/%Y/%m/')

    remarks = models.TextField(blank=True)
    approval_status = models.CharField(max_length=20, choices=APPROVAL_CHOICES, default='in_review', db_index=True)
    current_step = models.ForeignKey(
        'accounts.WorkflowStep', related_name='+', on_delete=models.SET_NULL, null=True, blank=True,
    )
    final_approver = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='assigned_final_payments',
        verbose_name='Assigned Final Approver',
        help_text='Specific user chosen at Level 3 for final approval',
    )

    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='payment_claims')
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            # Same composite-index reasoning as banners.Proposal — covers
            # the reviewer queue / dashboard "Needs Your Attention" pattern
            # and the per-step dashboard breakdown.
            models.Index(fields=['current_step', '-created_at']),
            models.Index(fields=['approval_status', 'current_step']),
        ]

    def save(self, *args, **kwargs):
        for field in ('bill_file', 'work_order_file', 'proof_file', 'covering_letter_file'):
            file_field = getattr(self, field)
            if file_field and not file_field._committed:
                compressed = compress_image_field(file_field.file)
                if compressed is not None:
                    file_field.save(compressed.name, compressed, save=False)

        is_new = self._state.adding
        super().save(*args, **kwargs)
        if is_new and not self.payment_number:
            seq = NumberSequence.next_value('payment_claim')
            self.payment_number = f'{self.PAYMENT_NUMBER_PREFIX}{seq:04d}'
            super().save(update_fields=['payment_number'])

    @property
    def proposal(self):
        """The originating Proposal, via the Work Order — shown alongside
        the payment so a reviewer sees both document numbers together."""
        return self.work_order.proposal

    @property
    def stage_label(self):
        """Human display label: 'Pending <Role> Review' or 'Pending Final Approval (<User>)' while in review."""
        if self.approval_status == 'in_review':
            if self.final_approver and self.current_step and self.current_step.order > 3:
                name = self.final_approver.get_full_name() or self.final_approver.username
                return f'Pending Final Approval ({name})'
            if self.current_step_id:
                return f'Pending {self.current_step.role.name} Review'
        return self.get_approval_status_display()

    @classmethod
    def next_payment_number_preview(cls):
        """Preview of the number the next PaymentClaim will receive —
        shown on the upload form before submission. Read-only: does not
        advance the sequence."""
        seq = NumberSequence.objects.filter(key='payment_claim').first()
        next_value = (seq.last_value if seq else 0) + 1
        return f'{cls.PAYMENT_NUMBER_PREFIX}{next_value:04d}'

    def __str__(self):
        return self.payment_number or f'PaymentClaim #{self.pk}'
