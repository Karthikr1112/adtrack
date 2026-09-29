import os

from django import forms
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import UploadedFile

from .models import Proposal, Category, Subcategory, Department

# Server-side upload limits — the `accept=` attribute on the widgets is
# browser-side only and offers no real protection.
MAX_UPLOAD_SIZE_MB = 15
ALLOWED_CAPTION_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.webp', '.gif', '.pdf'}


def validate_upload_size(uploaded):
    """Rejects files above MAX_UPLOAD_SIZE_MB. Only checks fresh uploads —
    files already stored (edit forms) are left alone."""
    if isinstance(uploaded, UploadedFile) and uploaded.size > MAX_UPLOAD_SIZE_MB * 1024 * 1024:
        raise ValidationError(
            f'File is too large ({uploaded.size / (1024 * 1024):.1f} MB). '
            f'Maximum allowed size is {MAX_UPLOAD_SIZE_MB} MB.'
        )


def validate_caption_file(uploaded):
    """Size + extension check for the 3 caption uploads — images or PDF only."""
    if uploaded and isinstance(uploaded, UploadedFile):
        validate_upload_size(uploaded)
        ext = os.path.splitext(uploaded.name or '')[1].lower()
        if ext not in ALLOWED_CAPTION_EXTENSIONS:
            raise ValidationError(
                'Unsupported file type "%s". Allowed: %s.'
                % (ext or 'unknown', ', '.join(sorted(ALLOWED_CAPTION_EXTENSIONS)))
            )


def validate_caption_file_error(uploaded):
    """Same size + extension check as validate_caption_file, but returns an
    error message string (or None) instead of raising — for use outside a
    ModelForm, e.g. the approval-decision attachment upload."""
    try:
        validate_caption_file(uploaded)
    except ValidationError as exc:
        return ' '.join(exc.messages)
    return None


def validate_photo_upload(uploaded):
    """Full check for a photo-only upload (size + must be a real image).
    Returns an error message string, or None if the file is acceptable."""
    try:
        validate_upload_size(uploaded)
        forms.ImageField().clean(uploaded)
    except ValidationError as exc:
        return ' '.join(exc.messages)
    return None


class BootstrapFormMixin:
    """Applies Bootstrap form-control/form-select/form-check-input classes to every field."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            widget = field.widget
            if isinstance(widget, forms.CheckboxInput):
                css_class = 'form-check-input'
            elif isinstance(widget, (forms.Select, forms.SelectMultiple)):
                css_class = 'form-select'
            else:
                css_class = 'form-control'
            existing = widget.attrs.get('class', '')
            widget.attrs['class'] = (existing + ' ' + css_class).strip()


from decimal import Decimal, InvalidOperation as DecimalException

class BannerForm(BootstrapFormMixin, forms.ModelForm):
    """The Add/Edit Proposal form. Supports independent subcategory,
    multi-select execution stores, mandatory quotations 1 & 2, optional supporting
    attachment, and multiple dynamic sizing & pricing order items."""

    campaign = forms.ModelChoiceField(
        queryset=None, required=True, empty_label='Select a campaign',
        label='Campaign Name',
    )
    vendor = forms.ModelChoiceField(
        queryset=None, required=True, empty_label='Select a vendor',
    )
    category = forms.ModelChoiceField(
        queryset=None, required=True, empty_label='Select a category',
    )
    subcategory = forms.ModelChoiceField(
        queryset=None, required=True, empty_label='Select a subcategory',
    )
    department = forms.ModelChoiceField(
        queryset=None, required=True, empty_label='Select a department',
    )
    start_date = forms.DateField(required=True, widget=forms.DateInput(attrs={'type': 'date'}))
    end_date = forms.DateField(required=True, widget=forms.DateInput(attrs={'type': 'date'}))

    store = forms.ModelChoiceField(
        queryset=None, required=False, empty_label='Select a store',
        label='Select Store (Dropdown)',
    )
    location = forms.CharField(
        required=False, label='Store Name',
        widget=forms.TextInput(attrs={'placeholder': 'Enter store name'}),
    )
    location_photo = forms.FileField(
        required=False, label='Store / Location Image (Optional)',
        widget=forms.FileInput(attrs={'accept': 'image/*,application/pdf'}),
    )

    tax_rate = forms.TypedChoiceField(
        choices=Proposal.TAX_RATE_CHOICES,
        coerce=Decimal,
        required=False,
        initial=Decimal('0.18'),
        empty_value=Decimal('0.18'),
        label='Tax Rate',
        widget=forms.Select(attrs={
            'id': 'taxRateSelect',
            'class': 'form-select-sm py-0 ps-2 pe-4 fw-semibold text-dark border-secondary-subtle',
            'style': 'width: auto; height: 26px; font-size: 0.75rem; border-radius: 6px; background-color: #ffffff; cursor: pointer; display: inline-block;',
        }),
    )

    caption_1 = forms.FileField(
        required=False, label='Quotation 1 (Mandatory)',
        widget=forms.FileInput(attrs={'accept': 'image/*,application/pdf'}),
    )
    caption_2 = forms.FileField(
        required=False, label='Quotation 2 (Mandatory)',
        widget=forms.FileInput(attrs={'accept': 'image/*,application/pdf'}),
    )
    caption_3 = forms.FileField(
        required=False, label='Quotation 3 (Optional)',
        widget=forms.FileInput(attrs={'accept': 'image/*,application/pdf'}),
    )
    summary_attachment = forms.FileField(
        required=False, label='Supporting Attachment (Optional)',
        widget=forms.FileInput(attrs={'accept': 'image/*,application/pdf'}),
    )
    remarks = forms.CharField(
        required=True, label='Remarks / Justification',
        widget=forms.Textarea(attrs={'rows': 3, 'placeholder': 'Why this proposal — final notes before submitting for approval.'}),
    )

    class Meta:
        model = Proposal
        fields = [
            'campaign', 'vendor', 'start_date', 'end_date', 'category', 'subcategory', 'department',
            'store', 'location', 'location_photo', 'caption_1', 'caption_2', 'caption_3', 'summary_attachment', 'remarks',
            'tax_rate',
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from .models import Campaign, Vendor, Category, Subcategory, Department, Store
        self.fields['campaign'].queryset = Campaign.objects.all()
        self.fields['vendor'].queryset = Vendor.objects.all()
        self.fields['category'].queryset = Category.objects.all()
        self.fields['subcategory'].queryset = Subcategory.objects.all()
        self.fields['department'].queryset = Department.objects.all()
        self.fields['store'].queryset = Store.objects.all()

        if self.instance and self.instance.pk:
            if self.instance.store_id:
                self.fields['store'].initial = self.instance.store_id
            if self.instance.tax_rate is not None:
                self.fields['tax_rate'].initial = self.instance.tax_rate

    def clean_location_photo(self):
        f = self.cleaned_data.get('location_photo')
        if f:
            validate_caption_file(f)
        return f

    def clean_caption_1(self):
        f = self.cleaned_data.get('caption_1')
        has_existing = bool(self.instance and self.instance.pk and self.instance.caption_1)
        if not f and not has_existing:
            raise ValidationError('Quotation 1 is mandatory. Please upload an image or PDF file.')
        if f:
            validate_caption_file(f)
        return f

    def clean_caption_2(self):
        f = self.cleaned_data.get('caption_2')
        has_existing = bool(self.instance and self.instance.pk and self.instance.caption_2)
        if not f and not has_existing:
            raise ValidationError('Quotation 2 is mandatory. Please upload an image or PDF file.')
        if f:
            validate_caption_file(f)
        return f

    def clean_caption_3(self):
        f = self.cleaned_data.get('caption_3')
        if f:
            validate_caption_file(f)
        return f

    def clean_summary_attachment(self):
        f = self.cleaned_data.get('summary_attachment')
        if f:
            validate_caption_file(f)
        return f

    def clean(self):
        cleaned = super().clean()
        start_date = cleaned.get('start_date')
        end_date = cleaned.get('end_date')
        if start_date and end_date and end_date < start_date:
            self.add_error('end_date', 'End date cannot be before start date.')

        # Parse & validate dynamic order items from POST data
        store_names = self.data.getlist('item_store_name')
        medium_ids = self.data.getlist('item_medium')
        heights = self.data.getlist('item_height')
        widths = self.data.getlist('item_width')
        size_units = self.data.getlist('item_size_unit')
        quantities = self.data.getlist('item_quantity')
        unit_prices = self.data.getlist('item_unit_price')
        extra_charges = self.data.getlist('item_extra_charge')
        tax_rates = self.data.getlist('item_tax_rate')

        num_items = max(len(heights), len(widths), len(quantities), len(unit_prices), len(store_names), len(tax_rates))
        if num_items == 0:
            self.add_error(None, 'At least one order item is required in Sizing & Pricing.')
            return cleaned

        selected_store = cleaned.get('store')
        cleaned_items = []
        for i in range(num_items):
            s_name = store_names[i].strip() if i < len(store_names) else ''

            if not s_name and selected_store:
                s_name = selected_store.name

            if not s_name:
                self.add_error(None, f'Order #{i+1}: Store Name is required.')

            h_str = heights[i].strip() if i < len(heights) else ''
            w_str = widths[i].strip() if i < len(widths) else ''
            med_id = medium_ids[i].strip() if i < len(medium_ids) else ''
            unit = size_units[i].strip() if i < len(size_units) else 'feet'
            q_str = quantities[i].strip() if i < len(quantities) else '1'
            p_str = unit_prices[i].strip() if i < len(unit_prices) else '0'
            ec_str = extra_charges[i].strip() if i < len(extra_charges) else '0'
            tax_rate_str = tax_rates[i].strip() if i < len(tax_rates) else '0.18'

            try:
                h = Decimal(h_str)
                if h <= 0:
                    raise ValueError
            except (ValueError, TypeError, DecimalException):
                self.add_error(None, f'Order #{i+1}: Height must be a positive number.')
                continue

            try:
                w = Decimal(w_str)
                if w <= 0:
                    raise ValueError
            except (ValueError, TypeError, DecimalException):
                self.add_error(None, f'Order #{i+1}: Width must be a positive number.')
                continue

            try:
                qty = int(q_str)
                if qty < 1:
                    raise ValueError
            except (ValueError, TypeError):
                self.add_error(None, f'Order #{i+1}: Quantity must be at least 1.')
                continue

            try:
                price = Decimal(p_str)
                if price < 0:
                    raise ValueError
            except (ValueError, TypeError, DecimalException):
                self.add_error(None, f'Order #{i+1}: Unit price must be a non-negative number.')
                continue

            try:
                extra = Decimal(ec_str) if ec_str else Decimal('0.00')
                if extra < 0:
                    raise ValueError
            except (ValueError, TypeError, DecimalException):
                self.add_error(None, f'Order #{i+1}: Extra charge must be a non-negative number.')
                continue

            try:
                item_rate = Decimal(tax_rate_str)
            except (ValueError, TypeError, DecimalException):
                item_rate = Decimal('0.18')

            sqft = (h * w).quantize(Decimal('0.01'))
            base_total = ((sqft * Decimal(qty) * price) + extra).quantize(Decimal('0.01'))
            item_tax = (base_total * item_rate).quantize(Decimal('0.01'))
            item_grand = base_total + item_tax

            cleaned_items.append({
                'item_number': i + 1,
                'store_name': s_name,
                'medium_id': int(med_id) if med_id and med_id.isdigit() else None,
                'height': h,
                'width': w,
                'square_feet': sqft,
                'size_unit': unit if unit in dict(Proposal.SIZE_UNIT_CHOICES) else 'feet',
                'quantity': qty,
                'unit_price': price,
                'extra_charge': extra,
                'tax_rate': item_rate,
                'tax_amount': item_tax,
                'total_amount': base_total,
                'grand_total': item_grand,
            })

        if not self.errors and not cleaned_items:
            self.add_error(None, 'Please enter valid order details in Sizing & Pricing.')

        self.cleaned_items = cleaned_items
        return cleaned

    def save(self, commit=True):
        from .models import ProposalItem
        instance = super().save(commit=False)

        tax_rate_val = self.cleaned_data.get('tax_rate')
        if tax_rate_val is not None:
            instance.tax_rate = Decimal(str(tax_rate_val))

        store = self.cleaned_data.get('store')
        instance.store = store

        if hasattr(self, 'cleaned_items') and self.cleaned_items:
            first_item = self.cleaned_items[0]
            instance.size = f"{first_item['height']} x {first_item['width']}"
            instance.size_unit = first_item['size_unit']
            instance.quantity = sum(item['quantity'] for item in self.cleaned_items)
            instance.unit_price = first_item['unit_price']
            instance.extra_charge = sum(item['extra_charge'] for item in self.cleaned_items)
            total_amount = sum(item['total_amount'] for item in self.cleaned_items)
            total_tax = sum(item['tax_amount'] for item in self.cleaned_items)
            instance.total_amount = total_amount
            instance.tax_amount = total_tax
            instance.grand_total = total_amount + total_tax
            if self.cleaned_items:
                instance.tax_rate = self.cleaned_items[0]['tax_rate']

            # Auto-populate location on Proposal from items
            store_names = [it['store_name'] for it in self.cleaned_items if it.get('store_name')]
            if store_names:
                instance.location = ", ".join(store_names) if len(store_names) <= 3 else f"{store_names[0]} (+{len(store_names)-1} more)"
            elif store:
                instance.location = store.name

        if commit:
            instance.save()
            self.save_m2m()
            if store:
                instance.stores.add(store)
            if hasattr(self, 'cleaned_items') and self.cleaned_items:
                instance.items.all().delete()
                for it in self.cleaned_items:
                    ProposalItem.objects.create(
                        proposal=instance,
                        item_number=it['item_number'],
                        store=store,
                        store_name=it['store_name'],
                        medium_id=it['medium_id'],
                        height=it['height'],
                        width=it['width'],
                        square_feet=it['square_feet'],
                        size_unit=it['size_unit'],
                        quantity=it['quantity'],
                        unit_price=it['unit_price'],
                        extra_charge=it['extra_charge'],
                        tax_rate=it['tax_rate'],
                        tax_amount=it['tax_amount'],
                        total_amount=it['total_amount'],
                        grand_total=it['grand_total'],
                    )
                instance.compute_totals()
                instance.save(update_fields=['total_amount', 'tax_amount', 'grand_total', 'tax_rate'])
        return instance
