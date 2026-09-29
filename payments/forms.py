from django import forms

from banners.forms import BootstrapFormMixin, validate_caption_file
from banners.models import WorkOrder
from .models import PaymentClaim


class WorkOrderSelect(forms.Select):
    """Adds data-proposal="PRO-MKT-0001" to every <option> so the upload
    page's JS can show the linked Proposal Number the moment a Work Order
    is picked, without any extra database query."""

    def create_option(self, name, value, label, selected, index, subindex=None, attrs=None):
        option = super().create_option(name, value, label, selected, index, subindex, attrs)
        instance = getattr(value, 'instance', None)
        if instance is not None:
            option['attrs']['data-proposal'] = instance.proposal.proposal_number or ''
        return option


class PaymentClaimForm(BootstrapFormMixin, forms.ModelForm):
    """The Payments Upload form — bill, work order copy, proof and covering
    letter, against a chosen Work Order. Same required-upload pattern the
    project already uses for proposal captions."""

    work_order = forms.ModelChoiceField(
        queryset=None, required=True, empty_label='Select a work order',
        label='Work Order Number', widget=WorkOrderSelect,
    )
    remarks = forms.CharField(
        required=True, label='Remarks',
        widget=forms.Textarea(attrs={'rows': 3, 'placeholder': 'Notes for the reviewer — required before submitting.'}),
    )

    class Meta:
        model = PaymentClaim
        fields = ['work_order', 'bill_file', 'work_order_file', 'proof_file', 'covering_letter_file', 'remarks']
        widgets = {
            'bill_file': forms.FileInput(attrs={'accept': 'image/*,application/pdf'}),
            'work_order_file': forms.FileInput(attrs={'accept': 'image/*,application/pdf'}),
            'proof_file': forms.FileInput(attrs={'accept': 'image/*,application/pdf'}),
            'covering_letter_file': forms.FileInput(attrs={'accept': 'image/*,application/pdf'}),
        }
        labels = {
            'bill_file': 'Bill Upload',
            'work_order_file': 'Work Order Upload',
            'proof_file': 'Proof Upload',
            'covering_letter_file': 'Covering Letter Upload',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['work_order'].queryset = WorkOrder.objects.select_related(
            'proposal', 'proposal__campaign'
        ).order_by('-created_at')
        for name in ('bill_file', 'work_order_file', 'proof_file', 'covering_letter_file'):
            self.fields[name].required = True

    def clean_bill_file(self):
        f = self.cleaned_data.get('bill_file')
        validate_caption_file(f)
        return f

    def clean_work_order_file(self):
        f = self.cleaned_data.get('work_order_file')
        validate_caption_file(f)
        return f

    def clean_proof_file(self):
        f = self.cleaned_data.get('proof_file')
        validate_caption_file(f)
        return f

    def clean_covering_letter_file(self):
        f = self.cleaned_data.get('covering_letter_file')
        validate_caption_file(f)
        return f
