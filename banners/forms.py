import os

from django import forms
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import UploadedFile

from .models import Banner, BannerPlacement, PlacementPhoto, BannerCost

# Server-side upload limits — the `accept=` attribute on the widgets is
# browser-side only and offers no real protection.
MAX_UPLOAD_SIZE_MB = 15
ALLOWED_BILL_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.webp', '.gif', '.pdf'}


def validate_upload_size(uploaded):
    """Rejects files above MAX_UPLOAD_SIZE_MB. Only checks fresh uploads —
    files already stored (edit forms) are left alone."""
    if isinstance(uploaded, UploadedFile) and uploaded.size > MAX_UPLOAD_SIZE_MB * 1024 * 1024:
        raise ValidationError(
            f'File is too large ({uploaded.size / (1024 * 1024):.1f} MB). '
            f'Maximum allowed size is {MAX_UPLOAD_SIZE_MB} MB.'
        )


def validate_photo_upload(uploaded):
    """Full check for photos handled outside a form (the wizard/edit pages
    read site_photo straight from request.FILES). Returns an error message
    string, or None if the file is acceptable."""
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


class BannerForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Banner
        fields = ['poster_name', 'banner_type', 'width', 'height', 'size_unit', 'material', 'status']


class BannerPlacementForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = BannerPlacement
        fields = ['location_name', 'address', 'latitude', 'longitude', 'placed_date', 'removal_date']
        widgets = {
            'placed_date': forms.DateInput(attrs={'type': 'date'}),
            'removal_date': forms.DateInput(attrs={'type': 'date'}),
            'latitude': forms.HiddenInput(attrs={'data-geo': 'lat'}),
            'longitude': forms.HiddenInput(attrs={'data-geo': 'lng'}),
        }


class PlacementPhotoForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = PlacementPhoto
        fields = ['photo', 'photo_latitude', 'photo_longitude']
        widgets = {
            'photo': forms.FileInput(attrs={'accept': 'image/*', 'capture': 'environment'}),
            'photo_latitude': forms.HiddenInput(attrs={'data-geo': 'lat'}),
            'photo_longitude': forms.HiddenInput(attrs={'data-geo': 'lng'}),
        }

    def clean_photo(self):
        photo = self.cleaned_data.get('photo')
        if photo:
            validate_upload_size(photo)
        return photo


class BannerCostForm(BootstrapFormMixin, forms.ModelForm):
    printing_cost = forms.DecimalField(max_digits=10, decimal_places=2, required=True, label="Printing cost")
    installation_cost = forms.DecimalField(max_digits=10, decimal_places=2, required=True, label="Installation cost")
    rental_cost = forms.DecimalField(max_digits=10, decimal_places=2, required=True, label="Rental cost")

    class Meta:
        model = BannerCost
        fields = ['printing_cost', 'installation_cost', 'rental_cost', 'vendor_name', 'bill_photo', 'bill_number', 'paid_on']
        widgets = {
            'paid_on': forms.DateInput(attrs={'type': 'date'}),
            'bill_photo': forms.FileInput(attrs={'accept': 'image/*,application/pdf'}),
        }

    def clean_bill_photo(self):
        bill = self.cleaned_data.get('bill_photo')
        if bill and isinstance(bill, UploadedFile):
            validate_upload_size(bill)
            ext = os.path.splitext(bill.name or '')[1].lower()
            if ext not in ALLOWED_BILL_EXTENSIONS:
                raise ValidationError(
                    'Unsupported file type "%s". Allowed: %s.'
                    % (ext or 'unknown', ', '.join(sorted(ALLOWED_BILL_EXTENSIONS)))
                )
        return bill
