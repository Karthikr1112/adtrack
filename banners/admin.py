from django.contrib import admin
from .models import (
    Proposal, ProposalItem, Campaign, Vendor, Category, Subcategory, Department,
    Medium, Store, ApprovalAction, WorkOrder
)


@admin.register(Campaign)
class CampaignAdmin(admin.ModelAdmin):
    list_display = ('name',)
    search_fields = ('name',)


@admin.register(Vendor)
class VendorAdmin(admin.ModelAdmin):
    list_display = ('name', 'contact_no', 'email', 'gst_no')
    search_fields = ('name', 'email', 'contact_no', 'gst_no', 'address')


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ('name',)
    search_fields = ('name',)


@admin.register(Subcategory)
class SubcategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'category')
    list_filter = ('category',)
    search_fields = ('name',)


@admin.register(Department)
class DepartmentAdmin(admin.ModelAdmin):
    list_display = ('name',)
    search_fields = ('name',)


@admin.register(Medium)
class MediumAdmin(admin.ModelAdmin):
    list_display = ('name',)
    search_fields = ('name',)


@admin.register(Store)
class StoreAdmin(admin.ModelAdmin):
    list_display = ('name', 'code')
    search_fields = ('name', 'code')


class ProposalItemInline(admin.TabularInline):
    model = ProposalItem
    extra = 0
    fields = ('item_number', 'category', 'subcategory', 'department', 'store_name', 'medium', 'height', 'width', 'square_feet', 'size_unit', 'quantity', 'unit_price', 'extra_charge', 'tax_rate', 'tax_amount', 'total_amount', 'grand_total')
    readonly_fields = ('square_feet', 'tax_amount', 'total_amount', 'grand_total')


class ApprovalActionInline(admin.TabularInline):
    model = ApprovalAction
    extra = 0
    readonly_fields = ('stage', 'action', 'actor', 'comment', 'attachment', 'created_at')
    can_delete = False


@admin.register(Proposal)
class ProposalAdmin(admin.ModelAdmin):
    list_display = ('proposal_number', 'campaign', 'vendor', 'category', 'subcategory', 'department', 'location', 'grand_total', 'approval_status', 'created_by', 'created_at')
    list_filter = ('approval_status', 'category', 'department', 'campaign', 'vendor')
    search_fields = ('proposal_number', 'location', 'campaign__name')
    readonly_fields = ('proposal_number', 'total_amount', 'tax_amount', 'grand_total')
    inlines = [ProposalItemInline, ApprovalActionInline]


@admin.register(WorkOrder)
class WorkOrderAdmin(admin.ModelAdmin):
    list_display = ('po_number', 'proposal', 'created_at')
    search_fields = ('po_number', 'proposal__proposal_number')
    readonly_fields = ('po_number',)
