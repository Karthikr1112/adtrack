from django.contrib import admin

# Register your models here.
from django.contrib import admin
from .models import Banner, BannerPlacement, PlacementPhoto, BannerCost


class BannerPlacementInline(admin.TabularInline):
    model = BannerPlacement
    extra = 0


@admin.register(Banner)
class BannerAdmin(admin.ModelAdmin):
    list_display = ('poster_name', 'banner_type', 'status', 'created_by', 'created_at')
    list_filter = ('status', 'banner_type')
    search_fields = ('poster_name',)
    inlines = [BannerPlacementInline]


@admin.register(BannerPlacement)
class BannerPlacementAdmin(admin.ModelAdmin):
    list_display = ('banner', 'location_name', 'placed_date', 'removal_date')
    list_filter = ('placed_date',)


@admin.register(PlacementPhoto)
class PlacementPhotoAdmin(admin.ModelAdmin):
    list_display = ('placement', 'captured_at', 'location_verified')
    list_filter = ('location_verified',)


@admin.register(BannerCost)
class BannerCostAdmin(admin.ModelAdmin):
    list_display = ('banner', 'vendor_name', 'total_cost_display', 'paid_on')

    def total_cost_display(self, obj):
        return obj.total_cost
    total_cost_display.short_description = 'Total cost'