from django.db import models

# Create your models here.
import os
from decimal import Decimal
from io import BytesIO

from django.core.files.base import ContentFile
from django.db import models
from django.contrib.auth.models import User

# Uploaded phone photos are often 4000px+ / 5-10 MB. Anything above this is
# resized and re-encoded as JPEG before hitting disk, so photo-heavy pages
# stay fast and storage doesn't balloon over years of use.
MAX_PHOTO_DIMENSION = 1920
PHOTO_JPEG_QUALITY = 82


def compress_image_field(field_file):
    """Shrinks an in-memory uploaded image to MAX_PHOTO_DIMENSION and JPEG.
    Returns a replacement ContentFile, or None if the file should be kept
    as-is (small already, not an image, or unreadable)."""
    try:
        from PIL import Image, ImageOps

        field_file.seek(0)
        img = Image.open(field_file)
        img.load()

        needs_resize = max(img.size) > MAX_PHOTO_DIMENSION
        needs_reencode = (img.format or '').upper() != 'JPEG'
        if not needs_resize and not needs_reencode:
            return None

        img = ImageOps.exif_transpose(img)
        if img.mode not in ('RGB', 'L'):
            img = img.convert('RGB')
        if needs_resize:
            img.thumbnail((MAX_PHOTO_DIMENSION, MAX_PHOTO_DIMENSION), Image.LANCZOS)

        buffer = BytesIO()
        img.save(buffer, format='JPEG', quality=PHOTO_JPEG_QUALITY, optimize=True)
        stem = os.path.splitext(os.path.basename(field_file.name or 'photo'))[0]
        return ContentFile(buffer.getvalue(), name=f'{stem}.jpg')
    except Exception:
        # Never block an upload because compression failed — store original.
        return None
    finally:
        try:
            field_file.seek(0)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Lookup tables — managed from the Django admin only. A proposal's Campaign /
# Category / Subcategory are picked from these via dropdowns; nobody types
# free text for them on the Add Proposal form.
# ---------------------------------------------------------------------------
class Campaign(models.Model):
    name = models.CharField(max_length=200, unique=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class Vendor(models.Model):
    name = models.CharField(max_length=200, unique=True)
    email = models.EmailField(max_length=254, blank=True, null=True, verbose_name='Mail ID')
    contact_no = models.CharField(max_length=20, blank=True, null=True, verbose_name='Contact No')
    gst_no = models.CharField(max_length=50, blank=True, null=True, verbose_name='GST No')
    address = models.TextField(blank=True, null=True, verbose_name='Address')

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class Category(models.Model):
    name = models.CharField(max_length=150, unique=True)

    class Meta:
        ordering = ['name']
        verbose_name_plural = 'Categories'

    def __str__(self):
        return self.name


class Department(models.Model):
    name = models.CharField(max_length=150, unique=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class Subcategory(models.Model):
    category = models.ForeignKey(Category, related_name='subcategories', on_delete=models.SET_NULL, null=True, blank=True)
    name = models.CharField(max_length=150)

    class Meta:
        ordering = ['name']
        verbose_name_plural = 'Subcategories'

    def __str__(self):
        return self.name


class Medium(models.Model):
    name = models.CharField(max_length=150, unique=True)

    class Meta:
        ordering = ['name']
        verbose_name_plural = 'Mediums'

    def __str__(self):
        return self.name


class Store(models.Model):
    name = models.CharField(max_length=150, unique=True)
    code = models.CharField(max_length=50, blank=True)

    class Meta:
        ordering = ['name']
        verbose_name_plural = 'Stores'

    def __str__(self):
        if self.code:
            return f"{self.name} ({self.code})"
        return self.name


class Proposal(models.Model):
    """A marketing proposal: campaign, schedule, category, sizing/pricing
    with 18% tax, supporting captions, and an approval workflow."""

    PROPOSAL_NUMBER_PREFIX = 'PRO-MKT-'

    # Approval chain: Executive creates -> however many steps the Approval
    # Flow (accounts.WorkflowStep) has configured, in order -> Approved.
    # `current_step` says exactly WHICH step is awaiting review right now;
    # `approval_status` is just the broad bucket, since the chain's own
    # length/roles are no longer fixed enough to have one choice per step.
    APPROVAL_CHOICES = [
        ('rework', 'Needs Rework'),
        ('in_review', 'In Review'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    ]

    TAX_RATE = Decimal('0.18')

    TAX_RATE_CHOICES = [
        (Decimal('0.00'), '0% (Exempt)'),
        (Decimal('0.05'), '5% GST'),
        (Decimal('0.10'), '10% Tax'),
        (Decimal('0.12'), '12% GST'),
        (Decimal('0.18'), '18% GST'),
        (Decimal('0.28'), '28% GST'),
    ]

    tax_rate = models.DecimalField(max_digits=4, decimal_places=2, default=Decimal('0.18'), choices=TAX_RATE_CHOICES, verbose_name='Tax Rate')

    # System-generated, e.g. "PRO-MKT-0001" — assigned once, right after the
    # first save (it's derived from the row's own id). Never user-editable.
    proposal_number = models.CharField(max_length=20, unique=True, null=True, blank=True, editable=False)

    # Lookup dropdowns — null=True at the model level (matches this project's
    # convention for optional-on-delete FKs, e.g. Profile.role) while the form
    # enforces them as required fields for data entry.
    campaign = models.ForeignKey(Campaign, related_name='proposals', on_delete=models.SET_NULL, null=True, blank=True)
    vendor = models.ForeignKey(Vendor, related_name='proposals', on_delete=models.SET_NULL, null=True, blank=True)
    category = models.ForeignKey(Category, related_name='proposals', on_delete=models.SET_NULL, null=True, blank=True)
    subcategory = models.ForeignKey(Subcategory, related_name='proposals', on_delete=models.SET_NULL, null=True, blank=True)
    department = models.ForeignKey(Department, related_name='proposals', on_delete=models.SET_NULL, null=True, blank=True)

    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)

    SIZE_UNIT_CHOICES = [
        ('feet', 'Feet'),
        ('inch', 'Inch'),
        ('meter', 'Meter'),
        ('cm', 'Centimeter'),
        ('piece', 'Pieces'),
    ]

    size = models.CharField(max_length=100, blank=True, help_text='e.g. 10ft x 20ft')
    size_unit = models.CharField(max_length=10, choices=SIZE_UNIT_CHOICES, default='feet')
    quantity = models.PositiveIntegerField(default=1)
    unit_price = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    # Optional — not mandatory like unit_price. Any one-off extra cost
    # (installation, transport, etc.) that should still count toward the
    # taxed total, not just get tacked on after tax.
    extra_charge = models.DecimalField(max_digits=12, decimal_places=2, default=0, blank=True)
    location = models.CharField(max_length=200, db_index=True, blank=True, verbose_name='Stores / Location')

    # Computed on every save() — never user-editable.
    total_amount = models.DecimalField(max_digits=14, decimal_places=2, editable=False, default=0)
    tax_amount = models.DecimalField(max_digits=14, decimal_places=2, editable=False, default=0)
    grand_total = models.DecimalField(max_digits=14, decimal_places=2, editable=False, default=0)

    caption_1 = models.FileField(upload_to='proposal_captions/%Y/%m/', blank=True, null=True)
    caption_2 = models.FileField(upload_to='proposal_captions/%Y/%m/', blank=True, null=True)
    caption_3 = models.FileField(upload_to='proposal_captions/%Y/%m/', blank=True, null=True)
    summary_attachment = models.FileField(upload_to='proposal_summaries/%Y/%m/', blank=True, null=True)

    # Final-summary mandatory field — a short justification/note the
    # submitter must give before the proposal can go to approval.
    remarks = models.TextField(blank=True, verbose_name='Remarks / Justification')

    approval_status = models.CharField(max_length=20, choices=APPROVAL_CHOICES, default='in_review', db_index=True)
    # Which configured step is currently awaiting review — null once the
    # document is approved/rejected/awaiting-rework-resubmission.
    current_step = models.ForeignKey(
        'accounts.WorkflowStep', related_name='+', on_delete=models.SET_NULL, null=True, blank=True,
    )
    final_approver = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='assigned_final_proposals',
        verbose_name='Assigned Final Approver',
        help_text='Specific user chosen at Level 3 for final approval',
    )
    awaiting_final_approver = models.BooleanField(
        default=False, db_index=True,
        help_text='True when Step 4 (CEO) has approved and proposal is awaiting the assigned final approver',
    )

    created_by = models.ForeignKey(User, related_name='banners_created', on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['created_at']),
            # Covers the reviewer queue / dashboard "Needs Your Attention"
            # pattern: filter(current_step_id__in=...).order_by('-created_at').
            models.Index(fields=['current_step', '-created_at']),
            # Covers the dashboard's per-step breakdown:
            # filter(approval_status='in_review').exclude(current_step__isnull=True)
            # .values('current_step__...').annotate(...).
            models.Index(fields=['approval_status', 'current_step']),
        ]

    @classmethod
    def next_proposal_number_preview(cls):
        """Best-effort preview of the number the *next* saved proposal will
        get — shown on the Add Proposal page before submission. Not a
        reservation: the real number is only assigned in save(), from the
        actual row id, so a concurrent submission could still claim it
        first. Purely informational."""
        last_id = cls.objects.order_by('-id').values_list('id', flat=True).first() or 0
        return f"{cls.PROPOSAL_NUMBER_PREFIX}{last_id + 1:04d}"

    @property
    def base_line_amount(self):
        """Line items base amount or legacy single quantity * unit_price"""
        if self.pk:
            items = list(self.items.all())
            if items:
                return sum((item.base_line_amount for item in items), Decimal('0.00'))
        return Decimal(self.quantity or 0) * Decimal(self.unit_price or 0)

    @property
    def total_quantity(self):
        """Sum of quantities across all order items, or legacy self.quantity."""
        if self.pk:
            items = list(self.items.all())
            if items:
                return sum((item.quantity or 0 for item in items))
        return self.quantity or 0

    @property
    def total_extra_charge(self):
        if self.pk:
            items = list(self.items.all())
            if items:
                return sum((Decimal(item.extra_charge or 0) for item in items), Decimal('0.00'))
        return Decimal(self.extra_charge or 0)

    @property
    def tax_percentage_display(self):
        if self.pk:
            items = list(self.items.all())
            if items:
                rates = {item.tax_rate for item in items if item.tax_rate is not None}
                if len(rates) == 1:
                    rate = rates.pop()
                    for val, label in self.TAX_RATE_CHOICES:
                        if Decimal(str(rate)) == val:
                            return '0% GST' if val == Decimal('0.00') else label
                    return f"{int(Decimal(str(rate)) * 100)}% GST"
                elif len(rates) > 1:
                    return 'Mixed GST'
        rate = self.tax_rate if self.tax_rate is not None else self.TAX_RATE
        for val, label in self.TAX_RATE_CHOICES:
            if Decimal(str(rate)) == val:
                return '0% GST' if val == Decimal('0.00') else label
        pct = int(Decimal(str(rate)) * 100)
        return f"{pct}% GST"

    def compute_totals(self):
        if self.pk:
            items = list(self.items.all())
            if items:
                self.quantity = sum((item.quantity or 0 for item in items))
                self.total_amount = sum((item.total_amount for item in items), Decimal('0.00'))
                self.tax_amount = sum((item.tax_amount for item in items), Decimal('0.00'))
                self.grand_total = self.total_amount + self.tax_amount
                return
        rate = Decimal(str(self.tax_rate if self.tax_rate is not None else self.TAX_RATE))
        if self.total_amount and self.total_amount > 0:
            self.tax_amount = (self.total_amount * rate).quantize(Decimal('0.01'))
            self.grand_total = self.total_amount + self.tax_amount
            return
        extra_charge = self.extra_charge or 0
        self.total_amount = self.base_line_amount + Decimal(extra_charge)
        self.tax_amount = (self.total_amount * rate).quantize(Decimal('0.01'))
        self.grand_total = self.total_amount + self.tax_amount

    def save(self, *args, **kwargs):
        self.compute_totals()
        for field_name in ('caption_1', 'caption_2', 'caption_3', 'summary_attachment'):
            field_file = getattr(self, field_name, None)
            if field_file and not field_file._committed:
                compressed = compress_image_field(field_file.file)
                if compressed is not None:
                    field_file.save(compressed.name, compressed, save=False)

        is_new = self._state.adding
        super().save(*args, **kwargs)

        if is_new and not self.proposal_number:
            # Only known once the row has a pk — one cheap follow-up UPDATE.
            self.proposal_number = f"{self.PROPOSAL_NUMBER_PREFIX}{self.pk:04d}"
            super().save(update_fields=['proposal_number'])

    @property
    def stage_label(self):
        """Human display label: 'Pending <Role> Review' or 'Pending Final Approval (<User>)' while in review."""
        if self.approval_status == 'in_review':
            if self.awaiting_final_approver and self.final_approver_id and self.final_approver:
                name = self.final_approver.get_full_name() or self.final_approver.username
                return f'Pending Final Approval ({name})'
            if self.current_step_id:
                return f'Pending {self.current_step.role.name} Review'
        return self.get_approval_status_display()

    def __str__(self):
        campaign_name = self.campaign.name if self.campaign_id else 'Untitled'
        return f"{self.proposal_number or 'Unsaved'} — {campaign_name}"


class ProposalItem(models.Model):
    proposal = models.ForeignKey(Proposal, related_name='items', on_delete=models.CASCADE)
    item_number = models.PositiveIntegerField(default=1)
    category = models.ForeignKey(Category, related_name='proposal_items', on_delete=models.SET_NULL, null=True, blank=True)
    subcategory = models.ForeignKey(Subcategory, related_name='proposal_items', on_delete=models.SET_NULL, null=True, blank=True)
    department = models.ForeignKey(Department, related_name='proposal_items', on_delete=models.SET_NULL, null=True, blank=True)
    medium = models.ForeignKey(Medium, related_name='proposal_items', on_delete=models.SET_NULL, null=True, blank=True)
    store_name = models.CharField(max_length=200, blank=True, verbose_name='Stores / Location')

    height = models.DecimalField(max_digits=10, decimal_places=2, default=0, blank=True)
    width = models.DecimalField(max_digits=10, decimal_places=2, default=0, blank=True)
    square_feet = models.DecimalField(max_digits=12, decimal_places=2, default=0, blank=True, verbose_name='Total Measurement')
    size_unit = models.CharField(max_length=10, choices=Proposal.SIZE_UNIT_CHOICES, default='feet')
    quantity = models.PositiveIntegerField(default=1)
    unit_price = models.DecimalField(max_digits=12, decimal_places=2, default=0, help_text='Rate per Measurement or Piece (₹)')
    extra_charge = models.DecimalField(max_digits=12, decimal_places=2, default=0, blank=True)
    total_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    tax_rate = models.DecimalField(max_digits=4, decimal_places=2, default=Decimal('0.18'), choices=Proposal.TAX_RATE_CHOICES, verbose_name='Tax Rate')
    tax_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0, verbose_name='Tax Amount')
    grand_total = models.DecimalField(max_digits=14, decimal_places=2, default=0, verbose_name='Item Grand Total')

    class Meta:
        ordering = ['item_number', 'id']

    @property
    def base_line_amount(self):
        """square_feet × quantity × unit_price, or quantity × unit_price for pieces"""
        qty = Decimal(self.quantity or 0)
        rate = Decimal(self.unit_price or 0)
        if self.size_unit in ('piece', 'pieces'):
            return (qty * rate).quantize(Decimal('0.01'))
        sqft = Decimal(self.square_feet or 0)
        return (sqft * qty * rate).quantize(Decimal('0.01'))

    @property
    def tax_percentage_display(self):
        rate = self.tax_rate if self.tax_rate is not None else Proposal.TAX_RATE
        for val, label in Proposal.TAX_RATE_CHOICES:
            if Decimal(str(rate)) == val:
                return '0% GST' if val == Decimal('0.00') else label
        pct = int(Decimal(str(rate)) * 100)
        return f"{pct}% GST"

    def compute_totals(self):
        h = Decimal(self.height or 0)
        w = Decimal(self.width or 0)
        self.square_feet = (h * w).quantize(Decimal('0.01'))
        extra = Decimal(self.extra_charge or 0)
        self.total_amount = self.base_line_amount + extra
        rate = Decimal(str(self.tax_rate if self.tax_rate is not None else Proposal.TAX_RATE))
        self.tax_amount = (self.total_amount * rate).quantize(Decimal('0.01'))
        self.grand_total = self.total_amount + self.tax_amount

    def save(self, *args, **kwargs):
        self.compute_totals()
        super().save(*args, **kwargs)

    def __str__(self):
        store_display = f" - {self.store_name}" if self.store_name else ""
        return f"Order #{self.item_number}{store_display} - {self.proposal.proposal_number or self.proposal.id}"


class ApprovalAction(models.Model):
    """Append-only audit trail of every step a document goes through — who
    acted, at which stage, what they did, and any comment they left. Shown
    on the detail/review pages so a later reviewer can see exactly what an
    earlier one said.

    Shared by Proposal AND payments.PaymentClaim (same Coordinator/Head/CEO
    review chain, same timeline UI) — exactly one of `proposal` /
    `payment_claim` is set per row; `subject` returns whichever it is."""

    # Keys match exactly what banner_approve_action passes through (the URL
    # action segment: 'approve'/'reject'/'rework') — using past-tense keys
    # here while the code stores present-tense values meant get_action_display()
    # never matched and the timeline's color/icon logic silently fell
    # through to its default styling for every Approve/Reject entry.
    ACTION_CHOICES = [
        ('submitted', 'Submitted'),
        ('resubmitted', 'Resubmitted'),
        ('approve', 'Approved'),
        ('reject', 'Rejected'),
        ('rework', 'Sent for Rework'),
    ]

    proposal = models.ForeignKey(Proposal, related_name='approval_history', on_delete=models.CASCADE, null=True, blank=True)
    payment_claim = models.ForeignKey('payments.PaymentClaim', related_name='approval_history', on_delete=models.CASCADE, null=True, blank=True)
    # A ready-to-display snapshot of who acted ("Executive", or whatever
    # the reviewing role was named at the time) — kept as plain text
    # rather than only a workflow_step FK so history reads correctly even
    # after that step is later renamed, reordered, or removed.
    stage = models.CharField(max_length=100)
    # The actual WorkflowStep this action happened at, when there was one
    # (submitted/resubmitted actions have none) — lets code reliably find
    # "the action where step X approved" (e.g. a mandatory attachment)
    # even though `stage` above is just free text.
    workflow_step = models.ForeignKey('accounts.WorkflowStep', related_name='+', on_delete=models.SET_NULL, null=True, blank=True)
    action = models.CharField(max_length=20, choices=ACTION_CHOICES)
    actor = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    comment = models.TextField(blank=True)
    # A step configured with require_attachment_on_approve requires an
    # attached file — kept on the action itself (not the Proposal) so if
    # it loops back through the same step again after a later rework,
    # each round keeps its
    # own file. Unused for payment claims.
    attachment = models.FileField(upload_to='approval_attachments/%Y/%m/', blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']
        indexes = [
            # Covers the common per-document history lookups — the
            # timeline (all actions for one proposal/claim, ordered by
            # created_at), the rework-note lookup
            # (filter(action='rework').order_by('-created_at').first()),
            # and the mandatory-attachment lookup
            # (filter(workflow_step__..., action='approve').order_by('-created_at')) —
            # all of which start from one proposal/claim's reverse FK.
            models.Index(fields=['proposal', 'action', 'created_at']),
            models.Index(fields=['payment_claim', 'action', 'created_at']),
        ]

    def save(self, *args, **kwargs):
        # Same treatment as Proposal captions: shrink images, leave PDFs
        # (or anything else) untouched.
        if self.attachment and not self.attachment._committed:
            compressed = compress_image_field(self.attachment.file)
            if compressed is not None:
                self.attachment.save(compressed.name, compressed, save=False)
        super().save(*args, **kwargs)

    @property
    def subject(self):
        """Whichever document this action belongs to — a Proposal or a
        PaymentClaim."""
        return self.proposal or self.payment_claim

    def __str__(self):
        return f"{self.subject} · {self.stage} · {self.get_action_display()}"


class WorkOrder(models.Model):
    """The Purchase Order / Work Order generated automatically the moment a
    proposal receives final CEO approval — one per proposal. Carries its
    own document number, independent of the proposal number, in the format
    "RRPL-<MM>-<YYYY>-MKT-0001"."""

    PO_NUMBER_PREFIX = 'RRPL'

    proposal = models.OneToOneField(Proposal, related_name='work_order', on_delete=models.CASCADE)
    po_number = models.CharField(max_length=30, unique=True, null=True, blank=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['created_at']),
        ]

    def save(self, *args, **kwargs):
        is_new = self._state.adding
        super().save(*args, **kwargs)
        if is_new and not self.po_number:
            # Only known once the row has a pk (for the sequence number) —
            # month/year come from the moment the PO is actually generated.
            stamp = self.created_at.strftime('%m-%Y')
            self.po_number = f"{self.PO_NUMBER_PREFIX}-{stamp}-MKT-{self.pk:04d}"
            super().save(update_fields=['po_number'])

    def __str__(self):
        return self.po_number or f"WorkOrder #{self.pk}"
