from django.contrib import admin

from banners.models import ApprovalAction
from .models import NumberSequence, PaymentClaim


class PaymentApprovalActionInline(admin.TabularInline):
    model = ApprovalAction
    fk_name = 'payment_claim'
    extra = 0
    readonly_fields = ('stage', 'action', 'actor', 'comment', 'attachment', 'created_at')
    can_delete = False


@admin.register(PaymentClaim)
class PaymentClaimAdmin(admin.ModelAdmin):
    list_display = ('payment_number', 'work_order', 'approval_status', 'created_by', 'created_at')
    list_filter = ('approval_status',)
    search_fields = ('payment_number', 'work_order__po_number', 'work_order__proposal__proposal_number')
    readonly_fields = ('payment_number',)
    inlines = [PaymentApprovalActionInline]


@admin.register(NumberSequence)
class NumberSequenceAdmin(admin.ModelAdmin):
    list_display = ('key', 'last_value')
