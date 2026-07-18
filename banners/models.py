from django.db import models

# Create your models here.
import os
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


class Banner(models.Model):
    BANNER_TYPE_CHOICES = [
        ('banner', 'Banner'),
        ('poster', 'Poster'),
        ('hoarding', 'Hoarding/Billboard'),
        ('standee', 'Standee'),
    ]
    SIZE_UNIT_CHOICES = [
        ('ft', 'Feet'),
        ('inch', 'Inch'),
        ('m', 'Meter'),
    ]
    STATUS_CHOICES = [
        ('planned', 'Planned'),
        ('placed', 'Placed'),
        ('removed', 'Removed'),
        ('damaged', 'Damaged'),
    ]

    poster_name = models.CharField(max_length=200, db_index=True)
    banner_type = models.CharField(max_length=20, choices=BANNER_TYPE_CHOICES, db_index=True)
    width = models.DecimalField(max_digits=6, decimal_places=2)
    height = models.DecimalField(max_digits=6, decimal_places=2)
    size_unit = models.CharField(max_length=10, choices=SIZE_UNIT_CHOICES, default='ft')
    material = models.CharField(max_length=100, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='planned')

    created_by = models.ForeignKey(User, related_name='banners_created', on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status']),
            models.Index(fields=['created_at']),
        ]

    def __str__(self):
        return self.poster_name


class BannerPlacement(models.Model):
    banner = models.ForeignKey(Banner, related_name='placements', on_delete=models.CASCADE)

    location_name = models.CharField(max_length=200, db_index=True)
    address = models.TextField()
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)

    placed_date = models.DateField(db_index=True)
    removal_date = models.DateField(null=True, blank=True)

    placed_by = models.ForeignKey(User, related_name='placements_done', on_delete=models.SET_NULL, null=True)

    class Meta:
        ordering = ['-placed_date']

    def __str__(self):
        return f"{self.banner.poster_name} @ {self.location_name}"


class PlacementPhoto(models.Model):
    placement = models.ForeignKey(BannerPlacement, related_name='photos', on_delete=models.CASCADE)
    photo = models.ImageField(upload_to='banner_photos/%Y/%m/')

    captured_at = models.DateTimeField(auto_now_add=True, db_index=True)
    photo_latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    photo_longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    location_verified = models.BooleanField(default=False, db_index=True)

    uploaded_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)

    class Meta:
        ordering = ['-captured_at']

    def save(self, *args, **kwargs):
        if self.photo and not self.photo._committed:
            compressed = compress_image_field(self.photo.file)
            if compressed is not None:
                self.photo.save(compressed.name, compressed, save=False)
        super().save(*args, **kwargs)


class BannerCost(models.Model):
    banner = models.ForeignKey(Banner, related_name='costs', on_delete=models.CASCADE)

    printing_cost = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    installation_cost = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    rental_cost = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)

    vendor_name = models.CharField(max_length=200, blank=True, db_index=True)
    bill_photo = models.FileField(upload_to='banner_bills/%Y/%m/', blank=True, null=True)
    bill_number = models.CharField(max_length=100, blank=True)
    paid_on = models.DateField(null=True, blank=True, db_index=True)

    recorded_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    def save(self, *args, **kwargs):
        # bill_photo also accepts PDFs — compress_image_field returns None
        # for anything that isn't an image, leaving the file untouched.
        if self.bill_photo and not self.bill_photo._committed:
            compressed = compress_image_field(self.bill_photo.file)
            if compressed is not None:
                self.bill_photo.save(compressed.name, compressed, save=False)
        super().save(*args, **kwargs)

    @property
    def total_cost(self):
        return (self.printing_cost or 0) + (self.installation_cost or 0) + (self.rental_cost or 0)

    def __str__(self):
        return f"Cost for {self.banner.poster_name} — {self.total_cost}"