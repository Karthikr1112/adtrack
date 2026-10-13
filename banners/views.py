from django.shortcuts import render

# Create your views here.
from io import BytesIO

from django.shortcuts import get_object_or_404, redirect
from django.core.paginator import Paginator
from django.contrib import messages
from django.contrib.auth.models import User
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.views.generic import ListView, DetailView, CreateView
from django.urls import reverse_lazy, reverse
from django.http import HttpResponse, Http404
from django.template.loader import render_to_string
from django.conf import settings

import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.utils import get_column_letter

from accounts.decorators import role_required
from accounts.permissions import user_has_permission, reviewable_stages, can_edit_record, is_personal_view
from .models import Proposal, ProposalItem, Campaign, Vendor, Category, Subcategory, Department, Medium, Store, WorkOrder
from .forms import BannerForm, validate_caption_file_error
from . import workflow


_LOGO_DATA_URI = None


def _logo_data_uri():
    """Base64 data URI for the company logo mark — embedded directly in the
    PDF (rather than referenced by static URL) since xhtml2pdf has no
    link_callback configured to resolve STATIC_URL paths on disk."""
    global _LOGO_DATA_URI
    if _LOGO_DATA_URI is None:
        import base64
        from pathlib import Path

        logo_path = Path(settings.BASE_DIR) / 'static' / 'img' / 'image.png'
        encoded = base64.b64encode(logo_path.read_bytes()).decode('ascii')
        _LOGO_DATA_URI = f'data:image/png;base64,{encoded}'
    return _LOGO_DATA_URI


def _detail_queryset():
    return Proposal.objects.select_related(
        'created_by', 'campaign', 'vendor', 'category', 'subcategory', 'department', 'current_step__role', 'final_approver'
    ).prefetch_related('items__category', 'items__subcategory', 'items__department', 'items__medium')


def _design_file_attachment(banner):
    """The design file uploaded at whichever step requires one (if any) —
    shown as its own card, separate from the Approval Timeline. Most
    recent one, in case the proposal went through rework and was
    re-approved more than once."""
    action = banner.approval_history.filter(
        workflow_step__require_attachment_on_approve=True, action='approve',
    ).exclude(attachment='').order_by('-created_at').first()
    return action.attachment if action else None


def _parse_date(value):
    """Parses a YYYY-MM-DD string from date inputs; returns None for anything
    malformed so a bad querystring can never crash the query."""
    from datetime import datetime
    if not value:
        return None
    try:
        return datetime.strptime(str(value).strip(), '%Y-%m-%d').date()
    except (TypeError, ValueError):
        return None


def _filtered_banners(request):
    """Shared filter/sort logic for the Proposals list page and its exports, so
    an export always matches exactly what's currently on screen.

    Same ownership rule as the Dashboard: a plain Executive only sees
    proposals they created themselves; anyone with broader responsibility
    (reviewer/admin/superuser) sees every proposal, org-wide.
    """
    queryset = _detail_queryset()
    if is_personal_view(request.user):
        queryset = queryset.filter(created_by=request.user)

    approval_status = request.GET.get('approval_status')
    if approval_status:
        queryset = queryset.filter(approval_status=approval_status)

    campaign_id = request.GET.get('campaign')
    if campaign_id:
        queryset = queryset.filter(campaign_id=campaign_id)

    vendor_id = request.GET.get('vendor')
    if vendor_id:
        queryset = queryset.filter(vendor_id=vendor_id)

    category_id = request.GET.get('category')
    if category_id:
        queryset = queryset.filter(category_id=category_id)

    department_id = request.GET.get('department')
    if department_id:
        queryset = queryset.filter(department_id=department_id)

    search = request.GET.get('q', '').strip()
    if search:
        queryset = queryset.filter(
            Q(location__icontains=search) |
            Q(proposal_number__icontains=search) |
            Q(campaign__name__icontains=search) |
            Q(vendor__name__icontains=search)
        )

    # Date filter: date_range ("2026-10-01 to 2026-10-10" or single date) or date_from / date_to
    date_range = request.GET.get('date_range', '').strip()
    if date_range:
        parts = date_range.split(' to ')
        if len(parts) == 2:
            d_start = _parse_date(parts[0])
            d_end = _parse_date(parts[1])
            if d_start:
                queryset = queryset.filter(created_at__date__gte=d_start)
            if d_end:
                queryset = queryset.filter(created_at__date__lte=d_end)
        elif len(parts) == 1:
            d_start = _parse_date(parts[0])
            if d_start:
                queryset = queryset.filter(created_at__date=d_start)

    date_from = request.GET.get('date_from', '').strip()
    if date_from:
        d_from = _parse_date(date_from)
        if d_from:
            queryset = queryset.filter(created_at__date__gte=d_from)

    store = request.GET.get('store', '').strip()
    if store:
        queryset = queryset.filter(
            Q(location__iexact=store) | Q(items__store_name__iexact=store)
        ).distinct()

    date_to = request.GET.get('date_to', '').strip()
    if date_to:
        d_to = _parse_date(date_to)
        if d_to:
            queryset = queryset.filter(created_at__date__lte=d_to)

    sort = request.GET.get('sort', '-created_at')
    if sort not in ('-created_at', 'created_at', 'location', '-location', '-grand_total', 'grand_total'):
        sort = '-created_at'
    queryset = queryset.order_by(sort)

    return queryset


class BannerListView(LoginRequiredMixin, ListView):
    """Main Proposals list page. All roles with can_view_banners can view it."""
    model = Proposal
    template_name = 'banners/banner_list.html'
    context_object_name = 'banners'
    paginate_by = 25

    def get_queryset(self):
        return _filtered_banners(self.request)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['approval_choices'] = Proposal.APPROVAL_CHOICES
        context['campaign_choices'] = Campaign.objects.all()
        context['vendor_choices'] = Vendor.objects.all()
        context['category_choices'] = Category.objects.all()
        context['department_choices'] = Department.objects.all()
        context['store_choices'] = Store.objects.all()
        querydict = self.request.GET.copy()
        querydict.pop('page', None)
        context['querystring'] = querydict.urlencode()
        return context



class BannerDetailView(LoginRequiredMixin, DetailView):
    model = Proposal
    template_name = 'banners/banner_detail.html'
    context_object_name = 'banner'

    def get_queryset(self):
        return _detail_queryset()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['my_review_stages'] = reviewable_stages(self.request.user)
        context['history'] = self.object.approval_history.select_related('actor').all()
        context['design_file'] = _design_file_attachment(self.object)
        return context


def _extract_submitted_items(post_data):
    category_ids = post_data.getlist('item_category')
    subcategory_ids = post_data.getlist('item_subcategory')
    department_ids = post_data.getlist('item_department')
    store_names = post_data.getlist('item_store_name')
    heights = post_data.getlist('item_height')
    widths = post_data.getlist('item_width')
    medium_ids = post_data.getlist('item_medium')
    size_units = post_data.getlist('item_size_unit')
    quantities = post_data.getlist('item_quantity')
    unit_prices = post_data.getlist('item_unit_price')
    extra_charges = post_data.getlist('item_extra_charge')
    tax_rates = post_data.getlist('item_tax_rate')
    num_items = max(len(heights), len(widths), len(store_names), len(category_ids), len(subcategory_ids), len(department_ids), len(tax_rates), 1)
    items = []
    for i in range(num_items):
        cat_id = category_ids[i] if i < len(category_ids) else ''
        subcat_id = subcategory_ids[i] if i < len(subcategory_ids) else ''
        dept_id = department_ids[i] if i < len(department_ids) else ''
        s_name = store_names[i] if i < len(store_names) else ''
        h = heights[i] if i < len(heights) else ''
        w = widths[i] if i < len(widths) else ''
        m = medium_ids[i] if i < len(medium_ids) else ''
        u = size_units[i] if i < len(size_units) else 'feet'
        q = quantities[i] if i < len(quantities) else '1'
        p = unit_prices[i] if i < len(unit_prices) else '0'
        ec = extra_charges[i] if i < len(extra_charges) else ''
        tr = tax_rates[i] if i < len(tax_rates) else '0.18'
        try:
            sqft = f"{(float(h) * float(w)):.2f}" if (h and w) else '0.00'
        except (ValueError, TypeError):
            sqft = '0.00'
        try:
            base_total = ((float(sqft) * float(q) * float(p)) + (float(ec) if ec else 0))
            tax_amt = base_total * float(tr)
            line_grand = base_total + tax_amt
            line_total_str = f"{base_total:.2f}"
            tax_amt_str = f"{tax_amt:.2f}"
            grand_total_str = f"{line_grand:.2f}"
        except (ValueError, TypeError):
            line_total_str = '0.00'
            tax_amt_str = '0.00'
            grand_total_str = '0.00'
        items.append({
            'item_number': i + 1,
            'category_id': int(cat_id) if cat_id and str(cat_id).isdigit() else '',
            'subcategory_id': int(subcat_id) if subcat_id and str(subcat_id).isdigit() else '',
            'department_id': int(dept_id) if dept_id and str(dept_id).isdigit() else '',
            'store_name': s_name,
            'medium_id': int(m) if m and str(m).isdigit() else '',
            'height': h,
            'width': w,
            'square_feet': sqft,
            'size_unit': u,
            'quantity': q,
            'unit_price': p,
            'extra_charge': ec,
            'tax_rate': tr,
            'tax_amount': tax_amt_str,
            'total_amount': line_total_str,
            'grand_total': grand_total_str,
        })
    return items


class BannerCreateView(LoginRequiredMixin, CreateView):
    """Add Proposal — a single page with every field on it. Submitting
    always saves as Pending Approval (the model's default); there is no
    separate 'reject' action here, only a Cancel link back to the list."""
    model = Proposal
    form_class = BannerForm
    template_name = 'banners/banner_add.html'

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and not user_has_permission(request.user, 'can_add_banner'):
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['next_proposal_number'] = Proposal.next_proposal_number_preview()
        context['categories'] = Category.objects.all()
        context['subcategories'] = Subcategory.objects.select_related('category').all()
        context['departments'] = Department.objects.all()
        context['mediums'] = Medium.objects.all()
        context['stores'] = Store.objects.all()
        context['size_units'] = Proposal.SIZE_UNIT_CHOICES
        context['tax_rates'] = Proposal.TAX_RATE_CHOICES
        if self.request.method == 'POST':
            context['items'] = _extract_submitted_items(self.request.POST)
        else:
            context['items'] = [{
                'item_number': 1,
                'category_id': '',
                'subcategory_id': '',
                'department_id': '',
                'store_name': '',
                'medium_id': '',
                'height': '',
                'width': '',
                'square_feet': '0.00',
                'size_unit': 'feet',
                'quantity': 1,
                'unit_price': 0,
                'extra_charge': '',
                'tax_rate': '0.18',
                'tax_amount': '0.00',
                'total_amount': '0.00',
                'grand_total': '0.00',
            }]
        return context

    def form_valid(self, form):
        form.instance.created_by = self.request.user
        # form.save() happens inside super().form_valid() — the proposal
        # number isn't assigned until then (it's derived from the new row's
        # own id), so the confirmation message is built after, not before.
        response = super().form_valid(form)
        workflow.submit(self.object, self.request.user)
        messages.success(
            self.request,
            f'Proposal {self.object.proposal_number} submitted for approval.'
        )

        workflow.invalidate_pending_counts_for_step(self.object.current_step)

        return response

    def get_success_url(self):
        return reverse('banner_detail', kwargs={'pk': self.object.pk})


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
    from django.db.models import Count, Sum
    from django.db.models.functions import TruncMonth
    from django.utils import timezone
    from payments.models import PaymentClaim

    search_query = request.GET.get('q', '')
    date_range = request.GET.get('date_range', '')
    approval_filter = request.GET.get('status', 'all')
    selected_store = request.GET.get('store', '').strip()

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

    # A plain Executive (can add proposals, but doesn't review anything and
    # doesn't manage users) sees only their OWN documents on the dashboard —
    # everyone else (Admin/Coordinator/Head/CEO/superuser) keeps the
    # org-wide view this dashboard has always shown. Same shared rule now
    # applied to the Proposals list/export and Payments Records pages.
    personal_view = is_personal_view(request.user)

    banners = Proposal.objects.select_related('created_by', 'campaign', 'category', 'department', 'current_step__role', 'final_approver')
    if personal_view:
        banners = banners.filter(created_by=request.user)

    if search_query:
        banners = banners.filter(location__icontains=search_query)
    if selected_store:
        banners = banners.filter(
            Q(location__iexact=selected_store) | Q(items__store_name__iexact=selected_store)
        ).distinct()
    if start_date:
        banners = banners.filter(created_at__date__gte=start_date)
    if end_date:
        banners = banners.filter(created_at__date__lte=end_date)
    if approval_filter and approval_filter != 'all':
        banners = banners.filter(approval_status=approval_filter)


    # "Total Grand Total" is real, committed spend — only proposals that
    # actually cleared the full approval chain count. A rejected or
    # still-pending proposal's grand_total was never actually spent, so it
    # must not inflate this number.
    total_spend = banners.filter(approval_status='approved').aggregate(total=Sum('grand_total'))['total'] or 0

    # 1. Spend Breakdown and Proposal Counts by Category
    category_costs = banners.exclude(category__isnull=True).values('category__name').annotate(
        total=Sum('grand_total'), count=Count('id')
    )
    category_labels = []
    category_data = []
    category_counts = []
    for cc in category_costs:
        category_labels.append(cc['category__name'] or 'Unknown')
        category_data.append(float(cc['total'] or 0))
        category_counts.append(cc['count'])

    # 1b. Same breakdown, but grouped by Vendor instead of Category.
    vendor_costs = banners.exclude(vendor__isnull=True).values('vendor__name').annotate(
        total=Sum('grand_total'), count=Count('id')
    )
    vendor_name_labels = []
    vendor_name_data = []
    vendor_name_counts = []
    for vc in vendor_costs:
        vendor_name_labels.append(vc['vendor__name'] or 'Unknown')
        vendor_name_data.append(float(vc['total'] or 0))
        vendor_name_counts.append(vc['count'])

    # 1c. Same breakdown again, grouped by Campaign.
    campaign_costs = banners.exclude(campaign__isnull=True).values('campaign__name').annotate(
        total=Sum('grand_total'), count=Count('id')
    )
    campaign_labels = []
    campaign_data = []
    campaign_counts = []
    for cpc in campaign_costs:
        campaign_labels.append(cpc['campaign__name'] or 'Unknown')
        campaign_data.append(float(cpc['total'] or 0))
        campaign_counts.append(cpc['count'])

    # 1d. Same breakdown again, grouped by Department.
    department_costs = banners.exclude(department__isnull=True).values('department__name').annotate(
        total=Sum('grand_total'), count=Count('id')
    )
    department_labels = []
    department_data = []
    department_counts = []
    for dc in department_costs:
        department_labels.append(dc['department__name'] or 'Unknown')
        department_data.append(float(dc['total'] or 0))
        department_counts.append(dc['count'])

    # 2. Monthly Spend and Proposal Count Trend
    monthly_trend = banners.annotate(month=TruncMonth('created_at')).values('month').annotate(
        total=Sum('grand_total'), count=Count('id')
    ).order_by('month')

    trend_labels = []
    trend_data = []
    trend_counts = []
    for item in monthly_trend:
        if item['month']:
            trend_labels.append(item['month'].strftime('%b %Y'))
            trend_data.append(float(item['total'] or 0))
            trend_counts.append(item['count'])

    # 3. Approval Status Distribution — for 'in_review' rows, broken down
    # by WHICH step they're waiting at (however many steps the Approval
    # Flow currently has), since 'in_review' alone doesn't say who's
    # holding it up.
    status_display_map = dict(Proposal.APPROVAL_CHOICES)
    # Colors assigned here (not guessed client-side from label text) since
    # an in-review step's label is now just whatever role name the
    # Approval Flow assigns — no fixed words to pattern-match against.
    BUCKET_COLORS = {'rework': '#0dcaf0', 'approved': '#198754', 'rejected': '#dc3545'}
    STEP_COLOR_PALETTE = ['#ffc107', '#fd7e14', '#6f42c1', '#d63384', '#20c997', '#6610f2']
    counts_by_status = {}
    status_labels = []
    status_data = []
    status_colors = []

    bucket_counts = dict(banners.filter(approval_status__in=('rework', 'approved', 'rejected')).values_list('approval_status').annotate(c=Count('id')))
    for bucket in ('rework', 'approved', 'rejected'):
        count = bucket_counts.get(bucket, 0)
        counts_by_status[bucket] = count
        if count:
            status_labels.append(status_display_map[bucket])
            status_data.append(count)
            status_colors.append(BUCKET_COLORS[bucket])

    in_review_by_step = banners.filter(approval_status='in_review').exclude(
        current_step__isnull=True
    ).values('current_step__order', 'current_step__role__name').annotate(count=Count('id')).order_by('current_step__order')
    in_review_total = 0
    for i, row in enumerate(in_review_by_step):
        in_review_total += row['count']
        status_labels.append(f"Pending {row['current_step__role__name']} Review")
        status_data.append(row['count'])
        status_colors.append(STEP_COLOR_PALETTE[i % len(STEP_COLOR_PALETTE)])
    counts_by_status['in_review'] = in_review_total

    # "Pending" on the dashboard KPI card means anywhere in the review
    # chain or awaiting rework — anything not yet at a final state.
    in_progress_stages = ('in_review', 'rework')

    # 4. Same Spend/Proposals breakdown again, grouped by Subcategory —
    # labeled "Category / Subcategory" (matching Subcategory.__str__) since
    # the same subcategory name can exist under different categories.
    subcategory_costs = banners.exclude(subcategory__isnull=True).values(
        'subcategory__name', 'subcategory__category__name',
    ).annotate(total=Sum('grand_total'), count=Count('id'))
    subcategory_labels = []
    subcategory_data = []
    subcategory_counts = []
    for sc in subcategory_costs:
        category_name = sc['subcategory__category__name']
        sub_name = sc['subcategory__name'] or 'Unknown'
        subcategory_labels.append(f'{category_name} / {sub_name}' if category_name else sub_name)
        subcategory_data.append(float(sc['total'] or 0))
        subcategory_counts.append(sc['count'])

    # 5. Month-over-month spend delta, shown as a badge on the Total Spend card.
    today = timezone.localdate()
    this_month_start = today.replace(day=1)
    if this_month_start.month == 1:
        last_month_start = this_month_start.replace(year=this_month_start.year - 1, month=12)
    else:
        last_month_start = this_month_start.replace(month=this_month_start.month - 1)
    this_month_spend = banners.filter(
        approval_status='approved', created_at__date__gte=this_month_start,
    ).aggregate(total=Sum('grand_total'))['total'] or 0
    last_month_spend = banners.filter(
        approval_status='approved', created_at__date__gte=last_month_start, created_at__date__lt=this_month_start,
    ).aggregate(total=Sum('grand_total'))['total'] or 0
    spend_delta_pct = round((this_month_spend - last_month_spend) / last_month_spend * 100, 1) if last_month_spend > 0 else None

    # ---- Payments ----
    # Same filter bar as Proposals (search/date range/status) applies here
    # too, so the Payments widgets never show all-time data while every
    # Proposal widget above them is scoped to the chosen filters.
    payment_claims = PaymentClaim.objects.select_related('work_order', 'work_order__proposal')
    if personal_view:
        payment_claims = payment_claims.filter(created_by=request.user)
    if search_query:
        payment_claims = payment_claims.filter(work_order__proposal__location__icontains=search_query)
    if selected_store:
        payment_claims = payment_claims.filter(
            Q(work_order__proposal__location__iexact=selected_store) |
            Q(work_order__proposal__items__store_name__iexact=selected_store)
        ).distinct()
    if start_date:
        payment_claims = payment_claims.filter(created_at__date__gte=start_date)
    if end_date:
        payment_claims = payment_claims.filter(created_at__date__lte=end_date)
    if approval_filter and approval_filter != 'all':
        payment_claims = payment_claims.filter(approval_status=approval_filter)

    payment_status_display_map = dict(PaymentClaim.APPROVAL_CHOICES)
    payment_status_labels = []
    payment_status_data = []
    payment_status_colors = []
    payment_counts_by_status = {}

    payment_bucket_counts = dict(payment_claims.filter(approval_status__in=('rework', 'approved', 'rejected')).values_list('approval_status').annotate(c=Count('id')))
    for bucket in ('rework', 'approved', 'rejected'):
        count = payment_bucket_counts.get(bucket, 0)
        payment_counts_by_status[bucket] = count
        if count:
            payment_status_labels.append(payment_status_display_map[bucket])
            payment_status_data.append(count)
            payment_status_colors.append(BUCKET_COLORS[bucket])

    payment_in_review_by_step = payment_claims.filter(approval_status='in_review').exclude(
        current_step__isnull=True
    ).values('current_step__order', 'current_step__role__name').annotate(count=Count('id')).order_by('current_step__order')
    payment_in_review_total = 0
    for i, row in enumerate(payment_in_review_by_step):
        payment_in_review_total += row['count']
        payment_status_labels.append(f"Pending {row['current_step__role__name']} Review")
        payment_status_data.append(row['count'])
        payment_status_colors.append(STEP_COLOR_PALETTE[i % len(STEP_COLOR_PALETTE)])
    payment_counts_by_status['in_review'] = payment_in_review_total

    # ---- "Needs Your Attention" — items this user can act on right now,
    # across both Proposals and Payments.
    my_stages = reviewable_stages(request.user)
    attention_proposals = []
    attention_payments = []
    if my_stages:
        attention_proposals = list(
            Proposal.objects.filter(current_step_id__in=my_stages)
            .select_related('campaign', 'current_step__role', 'final_approver').order_by('-created_at')[:5]
        )
        attention_payments = list(
            PaymentClaim.objects.filter(current_step_id__in=my_stages)
            .select_related('work_order', 'work_order__proposal', 'current_step__role', 'final_approver').order_by('-created_at')[:5]
        )

    context = {
        'is_personal_view': personal_view,
        'total_banners': sum(counts_by_status.values()),
        'approved_count': counts_by_status.get('approved', 0),
        'pending_count': sum(counts_by_status.get(s, 0) for s in in_progress_stages),
        'rejected_count': counts_by_status.get('rejected', 0),
        'payments_pending_count': sum(payment_counts_by_status.get(s, 0) for s in in_progress_stages),
        'total_spend': total_spend,
        'spend_delta_pct': spend_delta_pct,
        'recent_banners': banners.order_by('-created_at')[:5],

        'search_query': search_query,
        'date_range': date_range,
        'selected_status': approval_filter,
        'selected_store': selected_store,
        'store_choices': Store.objects.all(),
        'status_choices': Proposal.APPROVAL_CHOICES,


        'chart_vendor_labels': json.dumps(category_labels),
        'chart_vendor_data': json.dumps(category_data),
        'chart_vendor_counts': json.dumps(category_counts),
        'chart_trend_labels': json.dumps(trend_labels),
        'chart_trend_data': json.dumps(trend_data),
        'chart_trend_counts': json.dumps(trend_counts),
        'chart_status_labels': json.dumps(status_labels),
        'chart_status_data': json.dumps(status_data),
        'chart_status_colors': json.dumps(status_colors),

        'chart_vendor_name_labels': json.dumps(vendor_name_labels),
        'chart_vendor_name_data': json.dumps(vendor_name_data),
        'chart_vendor_name_counts': json.dumps(vendor_name_counts),
        'chart_subcategory_labels': json.dumps(subcategory_labels),
        'chart_subcategory_data': json.dumps(subcategory_data),
        'chart_subcategory_counts': json.dumps(subcategory_counts),
        'chart_campaign_labels': json.dumps(campaign_labels),
        'chart_campaign_data': json.dumps(campaign_data),
        'chart_campaign_counts': json.dumps(campaign_counts),
        'chart_department_labels': json.dumps(department_labels),
        'chart_department_data': json.dumps(department_data),
        'chart_department_counts': json.dumps(department_counts),

        # Payments
        'chart_payment_status_labels': json.dumps(payment_status_labels),
        'chart_payment_status_data': json.dumps(payment_status_data),
        'chart_payment_status_colors': json.dumps(payment_status_colors),

        'attention_proposals': attention_proposals,
        'attention_payments': attention_payments,
    }
    return render(request, 'banners/dashboard.html', context)


@role_required('can_edit_banner')
def banner_edit(request, pk):
    banner = get_object_or_404(Proposal, pk=pk)
    if not can_edit_record(request.user, banner):
        raise PermissionDenied(
            "You can only edit proposals you created, and only before they're approved."
        )
    needs_rework = banner.approval_status == 'rework'

    if request.method == 'POST':
        form = BannerForm(request.POST, request.FILES, instance=banner)
        if form.is_valid():
            form.save()
            if needs_rework:
                # Editing a reworked proposal resubmits it — back to the
                # first configured step.
                workflow.resubmit(banner, request.user)
                workflow.invalidate_pending_counts_for_step(banner.current_step)
                messages.success(request, f'Proposal {banner.proposal_number} resubmitted for approval.')
            else:
                messages.success(request, 'Proposal updated successfully.')
            return redirect('banner_detail', pk=banner.pk)
        messages.error(request, 'Please correct the errors below.')
        items = _extract_submitted_items(request.POST)
    else:
        form = BannerForm(instance=banner)
        banner_items = banner.items.select_related('category', 'subcategory', 'department', 'medium').all()
        if banner_items.exists():
            items = [{
                'item_number': it.item_number,
                'category_id': it.category_id or banner.category_id or '',
                'subcategory_id': it.subcategory_id or banner.subcategory_id or '',
                'department_id': it.department_id or banner.department_id or '',
                'store_name': it.store_name or banner.location or '',
                'medium_id': it.medium_id or '',
                'height': it.height,
                'width': it.width,
                'square_feet': f"{it.square_feet:.2f}",
                'size_unit': it.size_unit,
                'quantity': it.quantity,
                'unit_price': it.unit_price,
                'extra_charge': it.extra_charge if it.extra_charge else '',
                'tax_rate': f"{it.tax_rate:.2f}" if it.tax_rate is not None else '0.18',
                'tax_amount': f"{it.tax_amount:.2f}",
                'total_amount': f"{it.total_amount:.2f}",
                'grand_total': f"{it.grand_total:.2f}",
            } for it in banner_items]
        else:
            items = [{
                'item_number': 1,
                'category_id': banner.category_id or '',
                'subcategory_id': banner.subcategory_id or '',
                'department_id': banner.department_id or '',
                'store_name': banner.location or '',
                'medium_id': '',
                'height': banner.size.split('x')[0].strip() if 'x' in str(banner.size) else '10',
                'width': banner.size.split('x')[1].strip() if 'x' in str(banner.size) else '1',
                'square_feet': '10.00',
                'size_unit': banner.size_unit or 'feet',
                'quantity': banner.quantity or 1,
                'unit_price': banner.unit_price or 0,
                'extra_charge': banner.extra_charge if banner.extra_charge else '',
                'tax_rate': f"{banner.tax_rate:.2f}" if banner.tax_rate is not None else '0.18',
                'tax_amount': f"{banner.tax_amount:.2f}",
                'total_amount': f"{banner.total_amount:.2f}",
                'grand_total': f"{banner.grand_total:.2f}",
            }]

    # (field name, bound field, currently-stored file or None) for each
    # caption — lets the edit template show a download link for what's
    # already uploaded, next to the "replace it" file input.
    captions = [
        (name, form[name], getattr(banner, name) if getattr(banner, name) else None)
        for name in ('caption_1', 'caption_2', 'caption_3')
    ]
    summary_attachment_file = banner.summary_attachment if banner.summary_attachment else None

    return render(request, 'banners/banner_edit.html', {
        'form': form,
        'banner': banner,
        'captions': captions,
        'summary_attachment_file': summary_attachment_file,
        'needs_rework': needs_rework,
        'rework_note': banner.approval_history.filter(action='rework').order_by('-created_at').first() if needs_rework else None,
        'categories': Category.objects.all(),
        'subcategories': Subcategory.objects.select_related('category').all(),
        'departments': Department.objects.all(),
        'mediums': Medium.objects.all(),
        'stores': Store.objects.all(),
        'size_units': Proposal.SIZE_UNIT_CHOICES,
        'tax_rates': Proposal.TAX_RATE_CHOICES,
        'items': items,
    })


@role_required('can_delete_banner')
def banner_delete(request, pk):
    banner = get_object_or_404(_detail_queryset(), pk=pk)
    if request.method == 'POST':
        banner.delete()
        messages.success(request, 'Proposal deleted successfully.')
        return redirect('banner_list')
    return render(request, 'banners/banner_confirm_delete.html', {
        'banner': banner
    })


APPROVAL_FILL_COLORS = {
    'in_review': 'FFF3CD',
    'rework': 'CFE2FF',
    'approved': 'D1E7DD',
    'rejected': 'F8D7DA',
}


@login_required
def export_banners_excel(request):
    """
    Exports the Proposals list as an .xlsx file, honoring whatever filters are
    currently applied — the same queryset BannerListView uses, so the export
    always matches what's on screen.
    """
    banners = _filtered_banners(request)

    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = 'Proposals'

    headers = ['Proposal #', 'Campaign', 'Vendor', 'Category', 'Subcategory', 'Department', 'Start Date', 'End Date', 'Size',
               'Qty', 'Unit Price (₹)', 'Total (₹)', 'Tax 18% (₹)', 'Grand Total (₹)',
               'Location / Store', 'Status', 'Created By', 'Remarks']
    header_fill = PatternFill(start_color='0D6EFD', end_color='0D6EFD', fill_type='solid')
    header_font = Font(color='FFFFFF', bold=True)
    for col_index, header in enumerate(headers, start=1):
        cell = sheet.cell(row=1, column=col_index, value=header)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal='center', vertical='center')

    row_index = 2
    for banner in banners:
        sheet.cell(row=row_index, column=1, value=banner.proposal_number or '—')
        sheet.cell(row=row_index, column=2, value=banner.campaign.name if banner.campaign else '—')
        sheet.cell(row=row_index, column=3, value=banner.vendor.name if banner.vendor else '—')
        sheet.cell(row=row_index, column=4, value=banner.category.name if banner.category else '—')
        sheet.cell(row=row_index, column=5, value=str(banner.subcategory) if banner.subcategory else '—')
        sheet.cell(row=row_index, column=6, value=banner.department.name if banner.department else '—')
        sheet.cell(row=row_index, column=7, value=banner.start_date.strftime('%Y-%m-%d') if banner.start_date else '')
        sheet.cell(row=row_index, column=8, value=banner.end_date.strftime('%Y-%m-%d') if banner.end_date else '')
        sheet.cell(row=row_index, column=9, value=f'{banner.size} ({banner.get_size_unit_display()})' if banner.size else '')
        sheet.cell(row=row_index, column=10, value=banner.quantity)
        sheet.cell(row=row_index, column=11, value=float(banner.unit_price))
        sheet.cell(row=row_index, column=12, value=float(banner.total_amount))
        sheet.cell(row=row_index, column=13, value=float(banner.tax_amount))
        sheet.cell(row=row_index, column=14, value=float(banner.grand_total))
        sheet.cell(row=row_index, column=15, value=banner.location)
        status_cell = sheet.cell(row=row_index, column=16, value=banner.stage_label)
        status_cell.fill = PatternFill(
            start_color=APPROVAL_FILL_COLORS.get(banner.approval_status, 'FFFFFF'),
            end_color=APPROVAL_FILL_COLORS.get(banner.approval_status, 'FFFFFF'),
            fill_type='solid',
        )
        sheet.cell(row=row_index, column=17,
                   value=banner.created_by.username if banner.created_by else '—')
        sheet.cell(row=row_index, column=18, value=banner.remarks)
        row_index += 1

    column_widths = [16, 22, 18, 16, 20, 18, 12, 12, 16, 6, 14, 14, 12, 14, 24, 16, 16, 30]
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
    response['Content-Disposition'] = 'attachment; filename="proposals.xlsx"'
    return response


@login_required
def banner_approvals(request):
    from accounts.permissions import can_review_anything
    if not can_review_anything(request.user):
        raise PermissionDenied("You don't have permission to review proposals.")

    steps = reviewable_stages(request.user)

    if request.user.is_superuser:
        banners = Proposal.objects.filter(approval_status='in_review')
    else:
        banners = Proposal.objects.filter(
            approval_status='in_review'
        ).filter(
            Q(awaiting_final_approver=True, final_approver=request.user) |
            Q(awaiting_final_approver=False, current_step_id__in=steps)
        ).distinct()

    banners = banners.select_related(
        'created_by', 'campaign', 'vendor', 'category', 'department', 'current_step__role', 'final_approver'
    ).order_by('current_step__order', '-created_at')
    page_obj = Paginator(banners, 25).get_page(request.GET.get('page'))
    return render(request, 'banners/banner_approvals.html', {'banners': page_obj, 'page_obj': page_obj})


@login_required
def proposal_review(request, pk):
    """The 'summary box before approval' screen — full proposal details,
    the complete approval history (so a later reviewer sees earlier
    comments), and the step-appropriate action buttons with a comment box."""
    banner = get_object_or_404(_detail_queryset(), pk=pk)
    step = banner.current_step
    my_steps = reviewable_stages(request.user)
    all_steps = workflow.ordered_steps()

    if banner.approval_status == 'in_review':
        if banner.awaiting_final_approver:
            can_act = (request.user == banner.final_approver) or request.user.is_superuser
        elif step:
            can_act = (step.id in my_steps) or request.user.is_superuser
        else:
            can_act = False
    else:
        can_act = False

    can_rework = banner.awaiting_final_approver or (bool(step) and step.allow_rework)
    can_reject = banner.awaiting_final_approver or (bool(step) and getattr(step, 'can_reject', step.order > 2))
    attachment_required_on_approve = (not banner.awaiting_final_approver) and bool(step) and step.require_attachment_on_approve
    has_next_step = (not banner.awaiting_final_approver) and bool(step) and workflow.next_step(step, all_steps) is not None
    is_first_step = (not banner.awaiting_final_approver) and bool(step) and workflow.previous_step(step, all_steps) is None
    is_next_level = (not banner.awaiting_final_approver) and bool(step) and step.order in (1, 2)
    is_level_3 = (not banner.awaiting_final_approver) and bool(step) and step.order == 3
    is_final_step = banner.awaiting_final_approver or (bool(step) and (step.order > 3 or (workflow.next_step(step, all_steps) is None and not banner.final_approver)))

    final_approver_users = []
    if is_level_3:
        final_approver_users = User.objects.filter(
            is_active=True
        ).filter(
            Q(profile__is_admin_created=True) | Q(is_superuser=True)
        ).exclude(
            username__startswith='RR-'
        ).select_related('profile__role').order_by(
            'profile__role__name', 'first_name', 'username'
        )

    return render(request, 'banners/proposal_review.html', {
        'banner': banner,
        'history': banner.approval_history.select_related('actor').all(),
        'design_file': _design_file_attachment(banner),
        'can_act': can_act,
        'can_rework': can_rework,
        'can_reject': can_reject,
        'stage_label': banner.stage_label,
        'attachment_required_on_approve': attachment_required_on_approve,
        'is_first_step': is_first_step,
        'has_next_step': has_next_step,
        'is_next_level': is_next_level,
        'is_level_3': is_level_3,
        'is_final_step': is_final_step,
        'final_approver_users': final_approver_users,
    })


@login_required
def banner_approve_action(request, pk, action):
    if action not in ('approve', 'reject', 'rework'):
        raise Http404
    banner = get_object_or_404(Proposal.objects.select_related('current_step__role', 'final_approver'), pk=pk)

    if banner.approval_status != 'in_review':
        raise PermissionDenied("This proposal is not currently in review.")

    if banner.awaiting_final_approver:
        if request.user != banner.final_approver and not request.user.is_superuser:
            raise PermissionDenied("Only the assigned final approver can act on this proposal.")
        step = banner.current_step
    else:
        step = banner.current_step
        if step is None:
            raise PermissionDenied("This proposal has no active review step.")
        if step.id not in reviewable_stages(request.user) and not request.user.is_superuser:
            raise PermissionDenied("You don't have permission to act on this proposal at its current stage.")

    if request.method == 'POST':
        comment = request.POST.get('comment', '').strip()
        if not comment:
            messages.error(request, 'A comment is required for every decision.')
            return redirect('proposal_review', pk=banner.pk)

        if not banner.awaiting_final_approver:
            if action == 'rework' and not step.allow_rework:
                raise PermissionDenied("This stage has no rework option.")
            if action == 'reject' and not getattr(step, 'can_reject', step.order > 2):
                raise PermissionDenied("Step 1 and Step 2 do not have a reject option.")

            attachment = request.FILES.get('attachment')
            if step.require_attachment_on_approve and action == 'approve' and not attachment:
                messages.error(request, 'Please attach the design file (image or PDF) before approving.')
                return redirect('proposal_review', pk=banner.pk)
            if attachment:
                error = validate_caption_file_error(attachment)
                if error:
                    messages.error(request, error)
                    return redirect('proposal_review', pk=banner.pk)

        approver_user = None
        is_final_approval = False
        if not banner.awaiting_final_approver and action == 'approve' and step.order == 3:
            approval_mode = request.POST.get('approval_mode', 'next_level')
            if approval_mode == 'final_approve':
                is_final_approval = True
                if banner.final_approver_id is not None:
                    banner.final_approver = None
                    banner.save(update_fields=['final_approver'])
            else:
                final_approver_id = request.POST.get('final_approver')
                if final_approver_id:
                    try:
                        approver_user = User.objects.get(pk=final_approver_id, is_active=True)
                        banner.final_approver = approver_user
                        banner.save(update_fields=['final_approver'])
                    except User.DoesNotExist:
                        messages.error(request, 'Selected final approver is invalid or inactive.')
                        return redirect('proposal_review', pk=banner.pk)
                else:
                    # If unselected, proceed with normal workflow (clear any previously assigned final approver)
                    if banner.final_approver_id is not None:
                        banner.final_approver = None
                        banner.save(update_fields=['final_approver'])

        was_awaiting_final = banner.awaiting_final_approver
        old_step = step
        old_final_approver_id = banner.final_approver_id

        workflow.apply_action(
            banner, step, action, request.user,
            comment=comment,
            attachment=attachment if not was_awaiting_final else None,
            is_final_approval=is_final_approval,
        )

        if action == 'approve':
            if was_awaiting_final:
                verb = 'fully approved and Work Order generated'
            elif is_final_approval:
                verb = 'approved as final level and Work Order generated'
            elif old_step.order in (1, 2):
                upcoming = banner.current_step
                verb = f'sent to the next level ({upcoming.role.name} review)' if upcoming else 'sent to the next level'
            elif old_step.order == 3:
                upcoming = banner.current_step
                next_name = upcoming.role.name if upcoming else 'next level'
                if approver_user:
                    approver_name = approver_user.get_full_name() or approver_user.username
                    verb = f'approved and sent to {next_name} review (Final approval assigned to {approver_name})'
                else:
                    verb = f'approved and sent to {next_name} review'
            elif old_step.order == 4:
                if banner.awaiting_final_approver and banner.final_approver:
                    approver_name = banner.final_approver.get_full_name() or banner.final_approver.username
                    verb = f'approved by CEO and sent to {approver_name} for final approval'
                else:
                    verb = 'fully approved and Work Order generated'
            else:
                verb = 'fully approved and Work Order generated'
        else:
            verb = {'reject': 'rejected', 'rework': 'sent for rework'}[action]
        messages.success(request, f'Proposal {banner.proposal_number} {verb}.')

        # Invalidate badges
        workflow.invalidate_pending_counts_for_step(old_step, user_id=old_final_approver_id)
        workflow.invalidate_pending_counts_for_step(banner.current_step, user_id=(banner.final_approver_id if banner.awaiting_final_approver else None))
    return redirect('banner_approvals')


def _work_order_queryset():
    return WorkOrder.objects.select_related(
        'proposal', 'proposal__campaign', 'proposal__vendor',
        'proposal__category', 'proposal__subcategory', 'proposal__department', 'proposal__created_by',
    ).prefetch_related(
        'proposal__items__category', 'proposal__items__subcategory', 'proposal__items__department', 'proposal__items__medium'
    )


def _filtered_work_orders(request):
    orders = _work_order_queryset()
    if is_personal_view(request.user):
        orders = orders.filter(proposal__created_by=request.user)

    search = request.GET.get('q', '').strip()
    if search:
        orders = orders.filter(
            Q(po_number__icontains=search) |
            Q(proposal__proposal_number__icontains=search) |
            Q(proposal__campaign__name__icontains=search) |
            Q(proposal__vendor__name__icontains=search) |
            Q(proposal__location__icontains=search) |
            Q(proposal__department__name__icontains=search)
        )

    campaign_id = request.GET.get('campaign', '').strip()
    if campaign_id:
        orders = orders.filter(proposal__campaign_id=campaign_id)

    vendor_id = request.GET.get('vendor', '').strip()
    if vendor_id:
        orders = orders.filter(proposal__vendor_id=vendor_id)

    store = request.GET.get('store', '').strip()
    if store:
        orders = orders.filter(
            Q(proposal__location__iexact=store) |
            Q(proposal__items__store_name__iexact=store)
        ).distinct()

    date_range = request.GET.get('date_range', '').strip()
    if date_range:
        parts = date_range.split(' to ')
        if len(parts) == 2:
            d_start = _parse_date(parts[0])
            d_end = _parse_date(parts[1])
            if d_start:
                orders = orders.filter(created_at__date__gte=d_start)
            if d_end:
                orders = orders.filter(created_at__date__lte=d_end)
        elif len(parts) == 1:
            d_start = _parse_date(parts[0])
            if d_start:
                orders = orders.filter(created_at__date=d_start)

    date_from = request.GET.get('date_from', '').strip()
    if date_from:
        d_from = _parse_date(date_from)
        if d_from:
            orders = orders.filter(created_at__date__gte=d_from)

    date_to = request.GET.get('date_to', '').strip()
    if date_to:
        d_to = _parse_date(date_to)
        if d_to:
            orders = orders.filter(created_at__date__lte=d_to)

    sort = request.GET.get('sort', '-created_at').strip()
    if sort == 'created_at':
        orders = orders.order_by('created_at')
    elif sort == 'po_number':
        orders = orders.order_by('po_number')
    elif sort == '-grand_total':
        orders = orders.order_by('-proposal__grand_total')
    else:
        orders = orders.order_by('-created_at')

    return orders


@role_required('can_view_banners')
def work_order_list(request):
    """Every Work Order generated so far — one per fully-approved proposal.

    Same ownership rule as the Proposals/Payments lists: a plain
    Executive only sees Work Orders for proposals they created
    themselves; anyone with broader responsibility (reviewer/admin/
    superuser) sees every Work Order, org-wide."""
    orders = _filtered_work_orders(request)
    querydict = request.GET.copy()
    querydict.pop('page', None)
    querystring = querydict.urlencode()
    page_obj = Paginator(orders, 25).get_page(request.GET.get('page'))
    return render(request, 'banners/work_order_list.html', {
        'orders': page_obj,
        'page_obj': page_obj,
        'campaign_choices': Campaign.objects.all(),
        'vendor_choices': Vendor.objects.all(),
        'store_choices': Store.objects.all(),
        'querystring': querystring,
    })



@role_required('can_view_banners')
def work_order_detail(request, pk):
    """The on-screen Work Order, with a Download PDF button."""
    order = get_object_or_404(_work_order_queryset(), pk=pk)
    return render(request, 'banners/work_order_detail.html', {'order': order, 'banner': order.proposal})


@role_required('can_view_banners')
def work_order_download(request, pk):
    """Renders the same Work Order as a downloadable PDF."""
    from xhtml2pdf import pisa

    order = get_object_or_404(_work_order_queryset(), pk=pk)
    html = render_to_string('banners/work_order_pdf.html', {
        'order': order, 'banner': order.proposal, 'logo_data_uri': _logo_data_uri(),
    })

    buffer = BytesIO()
    result = pisa.CreatePDF(html, dest=buffer)
    if result.err:
        messages.error(request, 'Could not generate the PDF. Please try again.')
        return redirect('work_order_detail', pk=order.pk)

    response = HttpResponse(buffer.getvalue(), content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{order.po_number}.pdf"'
    return response
