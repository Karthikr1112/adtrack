from django.shortcuts import render

# Create your views here.
from io import BytesIO

from django.shortcuts import get_object_or_404, redirect
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.views.generic import ListView, DetailView, CreateView
from django.db.models import Sum, Prefetch, DecimalField
from django.db.models.functions import Coalesce
from django.urls import reverse_lazy, reverse
from django.http import HttpResponse
from django.conf import settings

import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.utils import get_column_letter

from accounts.decorators import role_required
from accounts.permissions import user_has_permission
from .models import Banner, BannerPlacement, PlacementPhoto, BannerCost
from .forms import (
    BannerForm, BannerPlacementForm, PlacementPhotoForm, BannerCostForm,
    validate_photo_upload,
)


def _detail_queryset():
    return Banner.objects.select_related('created_by').prefetch_related(
        Prefetch(
            'placements',
            queryset=BannerPlacement.objects.select_related('placed_by').prefetch_related('photos')
        ),
        'costs',
    )


def _detail_context(banner, **overrides):
    """Shared context for the banner detail page (Overview only) and its inline
    per-placement Add Photo forms — used by the detail view and upload_photo.
    """
    total = banner.costs.aggregate(
        total=Sum(Coalesce('printing_cost', 0, output_field=DecimalField())) +
              Sum(Coalesce('installation_cost', 0, output_field=DecimalField())) +
              Sum(Coalesce('rental_cost', 0, output_field=DecimalField()))
    )['total'] or 0
    context = {
        'banner': banner,
        'total_spend': total,
        'photo_form': PlacementPhotoForm(),
        'open_photo_placement_id': None,
        'photo_error_placement_id': None,
    }
    context.update(overrides)
    return context


def _wizard_context(wizard_banner, wizard_step, **overrides):
    """Shared context for the Add Banner page's wizard steps (Banner Details -> Add Placement
    -> Add Cost), all rendered on banner_add.html so the flow never leaves that page.
    """
    context = {
        'wizard_banner': wizard_banner,
        'wizard_step': wizard_step,
        'placement_form': BannerPlacementForm(),
        'cost_form': BannerCostForm(),
    }
    context.update(overrides)
    return context


def _filtered_banners(request):
    """Shared filter/sort logic for the Banners list page and its exports, so
    an export always matches exactly what's currently on screen (same status,
    type, search, and sort as the list view the user is looking at).
    """
    # Only costs are shown on the list page and in exports — prefetching
    # placements here would load every placement row for nothing.
    queryset = Banner.objects.select_related('created_by').prefetch_related('costs')

    status = request.GET.get('status')
    if status:
        queryset = queryset.filter(status=status)

    banner_type = request.GET.get('banner_type')
    if banner_type:
        queryset = queryset.filter(banner_type=banner_type)

    search = request.GET.get('q', '').strip()
    if search:
        queryset = queryset.filter(poster_name__icontains=search)

    sort = request.GET.get('sort', '-created_at')
    if sort not in ('-created_at', 'created_at', 'poster_name', '-poster_name'):
        sort = '-created_at'
    queryset = queryset.order_by(sort)

    return queryset


class BannerListView(LoginRequiredMixin, ListView):
    """
    Main list page. All roles can view banners.
    Uses select_related for the FK (created_by) and
    prefetch_related for the reverse FKs (placements, costs) — this turns
    what would be N+1 queries (one extra query per banner) into a fixed,
    small number of queries regardless of how many banners exist.
    """
    model = Banner
    template_name = 'banners/banner_list.html'
    context_object_name = 'banners'
    paginate_by = 10

    def get_queryset(self):
        return _filtered_banners(self.request)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['banner_type_choices'] = Banner.BANNER_TYPE_CHOICES
        context['status_choices'] = Banner.STATUS_CHOICES
        querydict = self.request.GET.copy()
        querydict.pop('page', None)
        context['querystring'] = querydict.urlencode()
        return context

class BannerDetailView(LoginRequiredMixin, DetailView):
    """
    Detail page — pulls the banner plus every placement and its photos,
    plus every cost record, in a bounded number of queries.
    """
    model = Banner
    template_name = 'banners/banner_detail.html'
    context_object_name = 'banner'

    def get_queryset(self):
        return _detail_queryset()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(_detail_context(self.object))
        try:
            context['open_photo_placement_id'] = int(self.request.GET.get('photo', 0)) or None
        except (TypeError, ValueError):
            context['open_photo_placement_id'] = None
        return context


class BannerCreateView(LoginRequiredMixin, CreateView):
    """
    Step 1 of the Add Banner wizard. Only Admin and Manager can create banners.
    On success, stays on this same URL (banner_add) but with ?step=placement&banner_id=<new id>
    so steps 2 and 3 (Add Placement, Add Cost) render right below on the same page.
    """
    model = Banner
    form_class = BannerForm
    template_name = 'banners/banner_add.html'

    def dispatch(self, request, *args, **kwargs):
        """Check if user can add banners."""
        if request.user.is_authenticated and not user_has_permission(request.user, 'can_add_banner'):
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        banner_id = self.request.GET.get('banner_id')
        wizard_banner = get_object_or_404(Banner, id=banner_id) if banner_id else None
        wizard_step = self.request.GET.get('step', 'banner')
        context.update(_wizard_context(wizard_banner, wizard_step))
        return context

    def form_valid(self, form):
        form.instance.created_by = self.request.user
        messages.success(self.request, 'Banner created. Now add a placement and cost below (optional).')
        return super().form_valid(form)

    def get_success_url(self):
        return f"{reverse('banner_add')}?step=placement&banner_id={self.object.pk}"


@role_required('can_add_placement')
def add_placement(request, banner_id):
    """Only reachable from the Add Banner wizard (banner_add.html) — the banner
    detail page is view-only and has no way to add further placements.
    """
    banner = get_object_or_404(Banner, id=banner_id)

    if request.method == 'POST':
        form = BannerPlacementForm(request.POST)
        # site_photo bypasses the form, so validate every file explicitly —
        # and before saving anything, so a bad file doesn't leave a
        # half-saved step.
        site_photos = request.FILES.getlist('site_photo')
        photo_error = _validate_photo_list(site_photos)
        if form.is_valid() and photo_error is None:
            placement = form.save(commit=False)
            placement.banner = banner
            placement.placed_by = request.user
            placement.save()
            banner.status = 'placed'
            banner.save(update_fields=['status'])

            _save_placement_photos(
                placement, site_photos,
                request.POST.get('site_photo_latitude'),
                request.POST.get('site_photo_longitude'),
                request.user,
            )

            messages.success(request, 'Placement recorded.')
            return redirect(f"{reverse('banner_add')}?step=cost&banner_id={banner.id}")

        if photo_error:
            form.add_error(None, f'Site photo: {photo_error}')
        messages.error(request, 'Please correct the errors below.')
        context = _wizard_context(banner, 'placement', placement_form=form)
        return render(request, 'banners/banner_add.html', context)

    return redirect('banner_detail', pk=banner.id)


@role_required('can_upload_photo')
def upload_photo(request, placement_id):
    placement = get_object_or_404(BannerPlacement, id=placement_id)

    if request.method == 'POST':
        form = PlacementPhotoForm(request.POST, request.FILES)
        photos = request.FILES.getlist('photo')
        photo_error = _validate_photo_list(photos)
        if form.is_valid() and photos and photo_error is None:
            _save_placement_photos(
                placement, photos,
                form.cleaned_data.get('photo_latitude'),
                form.cleaned_data.get('photo_longitude'),
                request.user,
            )
            count = len(photos)
            messages.success(
                request,
                f"{count} photo{'s' if count > 1 else ''} uploaded and location checked."
            )
            return redirect('banner_detail', pk=placement.banner_id)

        if photo_error:
            form.add_error(None, photo_error)
        messages.error(request, 'Please correct the errors below.')
        banner = get_object_or_404(_detail_queryset(), id=placement.banner_id)
        context = _detail_context(banner, photo_form=form, photo_error_placement_id=placement.id)
        return render(request, 'banners/banner_detail.html', context)

    url = reverse('banner_detail', kwargs={'pk': placement.banner_id})
    return redirect(f"{url}?photo={placement.id}")


def _validate_photo_list(files):
    """Validates every uploaded photo; returns the first error message
    (prefixed with the file name) or None if all are acceptable."""
    for f in files:
        error = validate_photo_upload(f)
        if error:
            return f'{f.name}: {error}'
    return None


def _save_placement_photos(placement, files, latitude, longitude, user):
    """Creates one PlacementPhoto per uploaded file. All photos from one
    submission share the same GPS pair (they're taken at the same spot)."""
    for f in files:
        photo = PlacementPhoto(
            placement=placement,
            photo=f,
            photo_latitude=latitude or None,
            photo_longitude=longitude or None,
            uploaded_by=user,
        )
        photo.location_verified = verify_location(placement, photo)
        photo.save()


def verify_location(placement, photo):
    """Returns True if the photo's GPS is within 100m of the claimed placement location."""
    if not (placement.latitude and placement.longitude and photo.photo_latitude and photo.photo_longitude):
        return False
    try:
        from geopy.distance import geodesic
        distance = geodesic(
            (float(placement.latitude), float(placement.longitude)),
            (float(photo.photo_latitude), float(photo.photo_longitude))
        ).meters
        return distance <= 100
    except Exception:
        return False


@role_required('can_add_cost')
def add_cost(request, banner_id):
    """Only reachable from the Add Banner wizard (banner_add.html) — the banner
    detail page is view-only and has no way to add further costs.
    """
    banner = get_object_or_404(Banner, id=banner_id)

    if request.method == 'POST':
        form = BannerCostForm(request.POST, request.FILES)
        if form.is_valid():
            cost = form.save(commit=False)
            cost.banner = banner
            cost.recorded_by = request.user
            cost.save()
            messages.success(request, 'Banner setup complete.')
            return redirect('banner_detail', pk=banner.id)

        messages.error(request, 'Please correct the errors below.')
        context = _wizard_context(banner, 'cost', cost_form=form)
        return render(request, 'banners/banner_add.html', context)

    return redirect('banner_detail', pk=banner.id)


def _parse_dashboard_date(value):
    """Parses a YYYY-MM-DD string from the date-range picker; returns None for
    anything malformed so a bad querystring can never crash the dashboard."""
    from datetime import datetime
    try:
        return datetime.strptime(value, '%Y-%m-%d').date()
    except (TypeError, ValueError):
        return None


@role_required('can_view_dashboard')
def dashboard(request):
    import json
    from django.db.models import Count, Sum, DecimalField, DateField, Q
    from django.db.models.functions import Coalesce, TruncMonth, TruncDate

    # Get query parameters for filtering
    search_query = request.GET.get('q', '')
    date_range = request.GET.get('date_range', '')
    status_filter = request.GET.get('status', 'all')

    start_date = None
    end_date = None
    if date_range:
        parts = date_range.split(' to ')
        if len(parts) == 2:
            start_date = _parse_dashboard_date(parts[0].strip())
            end_date = _parse_dashboard_date(parts[1].strip())
        elif len(parts) == 1:
            start_date = _parse_dashboard_date(parts[0].strip())
            end_date = start_date

    # Base querysets
    banners = Banner.objects.select_related('created_by')

    # Apply filters to banners
    if search_query:
        banners = banners.filter(poster_name__icontains=search_query)
    if start_date:
        banners = banners.filter(created_at__date__gte=start_date)
    if end_date:
        banners = banners.filter(created_at__date__lte=end_date)
    if status_filter and status_filter != 'all':
        banners = banners.filter(status=status_filter)

    # Total Spend calculated only from filtered banners
    total_spend = BannerCost.objects.filter(banner__in=banners).aggregate(
        total=Sum(Coalesce('printing_cost', 0, output_field=DecimalField())) +
              Sum(Coalesce('installation_cost', 0, output_field=DecimalField())) +
              Sum(Coalesce('rental_cost', 0, output_field=DecimalField()))
    )['total'] or 0

    # 1. Spend Breakdown and Banner Counts by Banner Type
    type_costs = BannerCost.objects.filter(banner__in=banners).values('banner__banner_type').annotate(
        total=Sum(
            Coalesce('printing_cost', 0, output_field=DecimalField()) +
            Coalesce('installation_cost', 0, output_field=DecimalField()) +
            Coalesce('rental_cost', 0, output_field=DecimalField())
        ),
        count=Count('banner', distinct=True)
    )
    type_display_map = dict(Banner.BANNER_TYPE_CHOICES)
    vendor_labels = []
    vendor_data = []
    vendor_counts = []
    for tc in type_costs:
        bt = tc['banner__banner_type']
        name = type_display_map.get(bt, bt) if bt else "Unknown"
        vendor_labels.append(name)
        vendor_data.append(float(tc['total']))
        vendor_counts.append(tc['count'])

    # 2. Monthly Spend and Banner Counts Trend
    # paid_on is a DateField and created_at a DateTimeField, so created_at is
    # truncated to a date first — Coalesce refuses mixed types otherwise.
    monthly_trend = BannerCost.objects.filter(banner__in=banners).annotate(
        date_ref=Coalesce('paid_on', TruncDate('created_at'), output_field=DateField())
    ).annotate(
        month=TruncMonth('date_ref')
    ).values('month').annotate(
        total=Sum(
            Coalesce('printing_cost', 0, output_field=DecimalField()) +
            Coalesce('installation_cost', 0, output_field=DecimalField()) +
            Coalesce('rental_cost', 0, output_field=DecimalField())
        ),
        count=Count('banner', distinct=True)
    ).order_by('month')

    trend_labels = []
    trend_data = []
    trend_counts = []
    for item in monthly_trend:
        if item['month']:
            trend_labels.append(item['month'].strftime('%b %Y'))
            trend_data.append(float(item['total'] or 0))
            trend_counts.append(item['count'])

    # 3. Status Distribution (based on filtered banners)
    status_counts = banners.values('status').annotate(count=Count('id'))
    status_display_map = dict(Banner.STATUS_CHOICES)
    status_labels = []
    status_data = []
    for sc in status_counts:
        status_labels.append(status_display_map.get(sc['status'], sc['status']))
        status_data.append(sc['count'])

    # 4. Geotag Verification Rate (filtered by placements of filtered banners)
    photo_counts = PlacementPhoto.objects.filter(placement__banner__in=banners).values('location_verified').annotate(count=Count('id'))
    verified_count = 0
    unverified_count = 0
    for pc in photo_counts:
        if pc['location_verified']:
            verified_count = pc['count']
        else:
            unverified_count = pc['count']

    # Aggregate counts in a single query
    banner_stats = banners.aggregate(
        total=Count('id'),
        placed=Count('id', filter=Q(status='placed')),
        planned=Count('id', filter=Q(status='planned')),
    )

    context = {
        'total_banners': banner_stats['total'],
        'placed_count': banner_stats['placed'],
        'planned_count': banner_stats['planned'],
        'total_spend': total_spend,
        'recent_banners': banners.prefetch_related('costs')[:5],
        
        # Current filters context
        'search_query': search_query,
        'date_range': date_range,
        'selected_status': status_filter,
        'status_choices': Banner.STATUS_CHOICES,
        
        # Chart JSON Data
        'chart_vendor_labels': json.dumps(vendor_labels),
        'chart_vendor_data': json.dumps(vendor_data),
        'chart_vendor_counts': json.dumps(vendor_counts),
        'chart_trend_labels': json.dumps(trend_labels),
        'chart_trend_data': json.dumps(trend_data),
        'chart_trend_counts': json.dumps(trend_counts),
        'chart_status_labels': json.dumps(status_labels),
        'chart_status_data': json.dumps(status_data),
        'chart_verified_count': verified_count,
        'chart_unverified_count': unverified_count,
    }
    return render(request, 'banners/dashboard.html', context)


@role_required('can_edit_banner')
def banner_edit(request, pk):
    banner = get_object_or_404(Banner, pk=pk)
    placement = banner.placements.first()
    cost = banner.costs.first()

    if request.method == 'POST':
        form = BannerForm(request.POST, instance=banner)
        
        # Check if placement data is provided or placement exists
        has_placement = placement is not None or any(request.POST.get(f) for f in ['location_name', 'address', 'placed_date'])
        if has_placement:
            placement_form = BannerPlacementForm(request.POST, instance=placement)
        else:
            placement_form = BannerPlacementForm(instance=placement)
            
        # Check if cost data is provided or cost exists
        has_cost = cost is not None or any(request.POST.get(f) for f in ['printing_cost', 'installation_cost', 'rental_cost'])
        if has_cost:
            cost_form = BannerCostForm(request.POST, request.FILES, instance=cost)
        else:
            cost_form = BannerCostForm(instance=cost)

        form_valid = form.is_valid()
        placement_valid = placement_form.is_valid() if has_placement else True
        cost_valid = cost_form.is_valid() if has_cost else True

        # site_photo bypasses the forms, so validate every file explicitly
        # before anything is saved.
        site_photos = request.FILES.getlist('site_photo')
        photo_error = _validate_photo_list(site_photos)
        if photo_error:
            placement_form.add_error(None, f'Site photo: {photo_error}')

        if form_valid and placement_valid and cost_valid and photo_error is None:
            form.save()

            if has_placement:
                pl = placement_form.save(commit=False)
                pl.banner = banner
                if not pl.placed_by:
                    pl.placed_by = request.user
                pl.save()

                # Save site photos if uploaded
                _save_placement_photos(
                    pl, site_photos,
                    request.POST.get('site_photo_latitude'),
                    request.POST.get('site_photo_longitude'),
                    request.user,
                )
                
            if has_cost:
                co = cost_form.save(commit=False)
                co.banner = banner
                if not co.recorded_by:
                    co.recorded_by = request.user
                co.save()
                
            messages.success(request, 'Banner details, placement, and cost updated successfully.')
            return redirect('banner_detail', pk=banner.pk)
        else:
            messages.error(request, 'Please correct the errors below.')
    else:
        form = BannerForm(instance=banner)
        placement_form = BannerPlacementForm(instance=placement)
        cost_form = BannerCostForm(instance=cost)

    return render(request, 'banners/banner_edit.html', {
        'form': form,
        'placement_form': placement_form,
        'cost_form': cost_form,
        'banner': banner
    })


@role_required('can_delete_banner')
def banner_delete(request, pk):
    banner = get_object_or_404(Banner, pk=pk)
    if request.method == 'POST':
        banner.delete()
        messages.success(request, 'Banner deleted successfully.')
        return redirect('banner_list')
    return render(request, 'banners/banner_confirm_delete.html', {
        'banner': banner
    })


STATUS_FILL_COLORS = {
    'planned': 'FFF3CD',
    'placed': 'D1E7DD',
    'removed': 'E2E3E5',
    'damaged': 'F8D7DA',
}


@login_required
def export_banners_excel(request):
    """
    Exports the Banners list as an .xlsx file, honoring whatever status/type/
    search/sort filters are currently applied — the same queryset BannerListView
    uses, so the export always matches what's on screen.
    """
    banners = _filtered_banners(request)

    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = 'Banners'

    headers = ['Poster Name', 'Type', 'Size', 'Status', 'Created By', 'Total Spend (₹)']
    header_fill = PatternFill(start_color='0D6EFD', end_color='0D6EFD', fill_type='solid')
    header_font = Font(color='FFFFFF', bold=True)
    for col_index, header in enumerate(headers, start=1):
        cell = sheet.cell(row=1, column=col_index, value=header)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal='center', vertical='center')

    row_index = 2
    for banner in banners:
        total_spend = sum((cost.total_cost for cost in banner.costs.all()), 0)
        sheet.cell(row=row_index, column=1, value=banner.poster_name)
        sheet.cell(row=row_index, column=2, value=banner.get_banner_type_display())
        sheet.cell(row=row_index, column=3, value=f'{banner.width} x {banner.height} {banner.get_size_unit_display()}')
        status_cell = sheet.cell(row=row_index, column=4, value=banner.get_status_display())
        status_cell.fill = PatternFill(
            start_color=STATUS_FILL_COLORS.get(banner.status, 'FFFFFF'),
            end_color=STATUS_FILL_COLORS.get(banner.status, 'FFFFFF'),
            fill_type='solid',
        )
        sheet.cell(row=row_index, column=5,
                   value=banner.created_by.username if banner.created_by else '—')
        spend_cell = sheet.cell(row=row_index, column=6, value=float(total_spend))
        spend_cell.number_format = '₹#,##0.00'
        row_index += 1

    column_widths = [28, 16, 22, 14, 16, 18]
    for col_index, width in enumerate(column_widths, start=1):
        sheet.column_dimensions[get_column_letter(col_index)].width = width

    sheet.freeze_panes = 'A2'

    buffer = BytesIO()
    workbook.save(buffer)
    buffer.seek(0)

    response = HttpResponse(
        buffer.read(),
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )
    response['Content-Disposition'] = 'attachment; filename="banners.xlsx"'
    return response


