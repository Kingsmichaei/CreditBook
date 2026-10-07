"""Owner console: platform-wide views for the SaaS owner to manage tenant businesses."""
import csv
from datetime import timedelta
from decimal import Decimal, InvalidOperation
from functools import wraps

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Count, DecimalField, OuterRef, Q, Subquery, Sum, Value
from django.db.models.functions import Coalesce, TruncMonth
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from billing.models import BillingLog
from core.models import Customer, Debt, Expense, Sale, Staff, Tenant, clear_current_tenant

from . import services
from .forms import (
    ActivateSubscriptionForm,
    DisableBusinessForm,
    EnableBusinessForm,
    ExtendTrialForm,
    TerminateSubscriptionForm,
)
from .models import AdminAction

PAGE_SIZE = 25
ZERO = Value(Decimal('0'), output_field=DecimalField(max_digits=14, decimal_places=2))

STATUS_FILTERS = dict(Tenant.SUBSCRIPTION_STATUS_CHOICES)
EXTRA_FILTERS = {
    'disabled': 'Disabled',
    'overdue': 'Renewal overdue',
    'trial_ending': 'Trial ending (7 days)',
}
SORTS = {
    'newest': '-created_at',
    'oldest': 'created_at',
    'name': 'business_name',
    'next_billing': 'next_billing_date',
    'revenue': '-revenue',
}


def platform_owner_required(view):
    """Restrict a view to superusers and lift tenant scoping so queries see every business."""
    @login_required
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_superuser:
            raise Http404
        # TenantMiddleware scopes TenantManager querysets to the owner's own business, if they have one.
        clear_current_tenant()
        return view(request, *args, **kwargs)
    return wrapper


def _subscription_price():
    try:
        return Decimal(str(settings.SUBSCRIPTION_PRICE_NGN or 0))
    except InvalidOperation:
        return Decimal('0')


def _month_starts(count, today):
    """First day of each of the last `count` months, oldest first."""
    months = []
    year, month = today.year, today.month
    for _ in range(count):
        months.append(today.replace(year=year, month=month, day=1))
        month -= 1
        if month == 0:
            year, month = year - 1, 12
    return list(reversed(months))


def _annotated_tenants():
    paid = BillingLog.objects.filter(tenant=OuterRef('pk'), status='success')
    revenue = paid.values('tenant').annotate(total=Sum('amount')).values('total')
    last_paid = paid.order_by('-created_at').values('created_at')[:1]
    return (
        Tenant.objects.select_related('owner')
        .annotate(
            member_count=Count('memberships', distinct=True),
            revenue=Coalesce(Subquery(revenue), ZERO),
            last_paid_at=Subquery(last_paid),
        )
    )


@platform_owner_required
def overview(request):
    today = timezone.localdate()
    month_start = today.replace(day=1)
    last_month_start = (month_start - timedelta(days=1)).replace(day=1)
    tenants = Tenant.objects.all()

    status_counts = dict(tenants.values_list('subscription_status').annotate(n=Count('id')))
    paying_active = tenants.filter(subscription_status='active', is_disabled=False).count()
    successful = BillingLog.objects.filter(status='success')

    def revenue_between(start, end=None):
        qs = successful.filter(created_at__date__gte=start)
        if end:
            qs = qs.filter(created_at__date__lt=end)
        return qs.aggregate(t=Sum('amount'))['t'] or Decimal('0')

    revenue_this_month = revenue_between(month_start)
    revenue_last_month = revenue_between(last_month_start, month_start)
    revenue_change = None
    if revenue_last_month:
        revenue_change = round((revenue_this_month - revenue_last_month) / revenue_last_month * 100, 1)

    # 12-month series for charts.
    months = _month_starts(12, today)
    revenue_by_month = {
        row['month'].date() if hasattr(row['month'], 'date') else row['month']: row['total']
        for row in successful.filter(created_at__date__gte=months[0])
        .annotate(month=TruncMonth('created_at')).values('month').annotate(total=Sum('amount'))
    }
    signups_by_month = {
        row['month'].date() if hasattr(row['month'], 'date') else row['month']: row['n']
        for row in tenants.filter(created_at__date__gte=months[0])
        .annotate(month=TruncMonth('created_at')).values('month').annotate(n=Count('id'))
    }

    status_rows = [
        {'key': key, 'label': label, 'count': status_counts.get(key, 0)}
        for key, label in Tenant.SUBSCRIPTION_STATUS_CHOICES
    ]
    total_tenants = sum(status_counts.values())
    trial_count = status_counts.get('trial', 0)
    ever_paid = successful.values('tenant').distinct().count()

    context = {
        'total_tenants': total_tenants,
        'active_count': status_counts.get('active', 0),
        'trial_count': trial_count,
        'at_risk_count': sum(status_counts.get(k, 0) for k in ('read_only', 'past_due', 'paused', 'suspended')),
        'cancelled_count': status_counts.get('cancelled', 0),
        'disabled_count': tenants.filter(is_disabled=True).count(),
        'new_this_month': tenants.filter(created_at__date__gte=month_start).count(),
        'mrr': _subscription_price() * paying_active,
        'arr': _subscription_price() * paying_active * 12,
        'subscription_price': _subscription_price(),
        'revenue_this_month': revenue_this_month,
        'revenue_last_month': revenue_last_month,
        'revenue_change': revenue_change,
        'revenue_all_time': successful.aggregate(t=Sum('amount'))['t'] or Decimal('0'),
        'failed_payments_30d': BillingLog.objects.filter(status='failed', created_at__gte=timezone.now() - timedelta(days=30)).count(),
        'conversion_rate': round(ever_paid / total_tenants * 100, 1) if total_tenants else 0,
        'overdue_count': tenants.filter(subscription_status='active', next_billing_date__lt=today).count(),
        'status_rows': status_rows,
        'chart_labels': [m.strftime('%b %Y') for m in months],
        'chart_revenue': [float(revenue_by_month.get(m, 0) or 0) for m in months],
        'chart_signups': [signups_by_month.get(m, 0) for m in months],
        'chart_status_labels': [r['label'] for r in status_rows],
        'chart_status_counts': [r['count'] for r in status_rows],
        'trials_ending': tenants.filter(
            subscription_status='trial', trial_ends_at__gte=today, trial_ends_at__lte=today + timedelta(days=7),
        ).select_related('owner').order_by('trial_ends_at')[:8],
        'recent_signups': tenants.select_related('owner').order_by('-created_at')[:6],
        'recent_payments': BillingLog.objects.select_related('tenant').order_by('-created_at')[:8],
        'recent_actions': AdminAction.objects.select_related('actor').order_by('-created_at')[:6],
    }
    return render(request, 'console/overview.html', context)


@platform_owner_required
def businesses(request):
    today = timezone.localdate()
    q = request.GET.get('q', '').strip()
    status = request.GET.get('status', '')
    sort = request.GET.get('sort', 'newest')

    qs = _annotated_tenants()
    if q:
        qs = qs.filter(
            Q(business_name__icontains=q) | Q(slug__icontains=q) | Q(owner__email__icontains=q)
            | Q(owner__username__icontains=q) | Q(owner__first_name__icontains=q) | Q(owner__last_name__icontains=q)
        )
    if status in STATUS_FILTERS:
        qs = qs.filter(subscription_status=status)
    elif status == 'disabled':
        qs = qs.filter(is_disabled=True)
    elif status == 'overdue':
        qs = qs.filter(subscription_status='active', next_billing_date__lt=today)
    elif status == 'trial_ending':
        qs = qs.filter(subscription_status='trial', trial_ends_at__gte=today, trial_ends_at__lte=today + timedelta(days=7))
    qs = qs.order_by(SORTS.get(sort, '-created_at'), '-pk')

    if request.GET.get('export') == 'csv':
        return _export_businesses_csv(qs)

    page = Paginator(qs, PAGE_SIZE).get_page(request.GET.get('page'))
    params = request.GET.copy()
    params.pop('page', None)
    return render(request, 'console/businesses.html', {
        'page': page,
        'q': q,
        'status': status,
        'sort': sort,
        'status_filters': STATUS_FILTERS,
        'extra_filters': EXTRA_FILTERS,
        'sorts': SORTS,
        'querystring': params.urlencode(),
        'today': today,
    })


def _export_businesses_csv(qs):
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="businesses-{timezone.localdate()}.csv"'
    writer = csv.writer(response)
    writer.writerow([
        'ID', 'Business', 'Owner', 'Owner email', 'Status', 'Disabled', 'Members', 'Created',
        'Trial ends', 'Subscription start', 'Next billing', 'Lifetime revenue',
    ])
    for t in qs:
        writer.writerow([
            t.pk, t.business_name, t.owner.get_full_name() or t.owner.username, t.owner.email,
            t.get_subscription_status_display(), 'yes' if t.is_disabled else 'no', t.member_count,
            t.created_at.date(), t.trial_ends_at or '', t.subscription_start or '', t.next_billing_date or '', t.revenue,
        ])
    return response


def _detail_context(tenant, **forms):
    defaults = {
        'activate_form': ActivateSubscriptionForm(initial={'amount': _subscription_price() or None}),
        'terminate_form': TerminateSubscriptionForm(),
        'trial_form': ExtendTrialForm(),
        'disable_form': DisableBusinessForm(),
        'enable_form': EnableBusinessForm(),
    }
    defaults.update(forms)
    today = timezone.localdate()
    month_start = today.replace(day=1)
    sales = Sale.objects.filter(tenant=tenant)
    logs = BillingLog.objects.filter(tenant=tenant)
    return {
        'tenant': tenant,
        'members': tenant.memberships.select_related('user').order_by('created_at'),
        'usage': {
            'customers': Customer.objects.filter(tenant=tenant).count(),
            'staff': Staff.objects.filter(tenant=tenant, is_active=True).count(),
            'sales_count': sales.count(),
            'sales_total': sales.aggregate(t=Sum('total'))['t'] or 0,
            'sales_this_month': sales.filter(date__gte=month_start).count(),
            'expenses_total': Expense.objects.filter(tenant=tenant).aggregate(t=Sum('amount'))['t'] or 0,
            'open_debts': Debt.objects.filter(tenant=tenant, is_paid=False).aggregate(t=Sum('amount'))['t'] or 0,
            'last_sale': sales.order_by('-created_at').values_list('created_at', flat=True).first(),
        },
        'billing_logs': logs.order_by('-created_at')[:20],
        'lifetime_revenue': logs.filter(status='success').aggregate(t=Sum('amount'))['t'] or 0,
        'actions': tenant.admin_actions.select_related('actor').order_by('-created_at')[:20],
        'has_card': bool(tenant.nomba_token_key),
        'today': today,
        **defaults,
    }


@platform_owner_required
def business_detail(request, pk):
    tenant = get_object_or_404(Tenant.objects.select_related('owner'), pk=pk)
    return render(request, 'console/business_detail.html', _detail_context(tenant))


@platform_owner_required
@require_POST
def business_action(request, pk, action):
    tenant = get_object_or_404(Tenant, pk=pk)
    actor = request.user

    if action == 'activate':
        form = ActivateSubscriptionForm(request.POST)
        if form.is_valid():
            d = form.cleaned_data
            tenant = services.activate_subscription(tenant, actor, d['days'], d['amount'], d['reference'], d['note'])
            messages.success(request, f'{tenant.business_name} is now subscribed until {tenant.next_billing_date:%b %d, %Y}.')
            return redirect('console:business_detail', pk=pk)
        form_key = 'activate_form'
    elif action == 'terminate':
        form = TerminateSubscriptionForm(request.POST)
        if form.is_valid():
            services.terminate_subscription(tenant, actor, form.cleaned_data['reason'], form.cleaned_data['remove_card'])
            messages.success(request, f'Subscription for {tenant.business_name} has been terminated.')
            return redirect('console:business_detail', pk=pk)
        form_key = 'terminate_form'
    elif action == 'extend_trial':
        form = ExtendTrialForm(request.POST)
        if form.is_valid():
            tenant = services.extend_trial(tenant, actor, form.cleaned_data['days'], form.cleaned_data['note'])
            messages.success(request, f'Trial extended to {tenant.trial_ends_at:%b %d, %Y}.')
            return redirect('console:business_detail', pk=pk)
        form_key = 'trial_form'
    elif action == 'disable':
        form = DisableBusinessForm(request.POST)
        if form.is_valid():
            services.set_disabled(tenant, actor, True, form.cleaned_data['reason'])
            messages.success(request, f'{tenant.business_name} has been disabled. Its members can no longer access the app.')
            return redirect('console:business_detail', pk=pk)
        form_key = 'disable_form'
    elif action == 'enable':
        form = EnableBusinessForm(request.POST)
        if form.is_valid():
            services.set_disabled(tenant, actor, False, form.cleaned_data['note'])
            messages.success(request, f'{tenant.business_name} has been re-enabled.')
            return redirect('console:business_detail', pk=pk)
        form_key = 'enable_form'
    else:
        raise Http404

    messages.error(request, 'Please correct the errors below.')
    context = _detail_context(tenant, **{form_key: form})
    context['open_modal'] = form_key
    return render(request, 'console/business_detail.html', context, status=400)


@platform_owner_required
def payments(request):
    q = request.GET.get('q', '').strip()
    status = request.GET.get('status', '')
    qs = BillingLog.objects.select_related('tenant').order_by('-created_at')
    if q:
        qs = qs.filter(Q(tenant__business_name__icontains=q) | Q(order_reference__icontains=q) | Q(nomba_txn_id__icontains=q))
    if status in dict(BillingLog.STATUS):
        qs = qs.filter(status=status)

    totals = dict(qs.values_list('status').annotate(t=Sum('amount')).order_by())
    page = Paginator(qs, PAGE_SIZE).get_page(request.GET.get('page'))
    params = request.GET.copy()
    params.pop('page', None)
    return render(request, 'console/payments.html', {
        'page': page,
        'q': q,
        'status': status,
        'statuses': BillingLog.STATUS,
        'total_success': totals.get('success') or 0,
        'total_failed': totals.get('failed') or 0,
        'total_pending': totals.get('pending') or 0,
        'querystring': params.urlencode(),
    })


@platform_owner_required
def activity(request):
    action = request.GET.get('action', '')
    qs = AdminAction.objects.select_related('actor', 'tenant').order_by('-created_at')
    if action in dict(AdminAction.ACTIONS):
        qs = qs.filter(action=action)
    page = Paginator(qs, PAGE_SIZE).get_page(request.GET.get('page'))
    params = request.GET.copy()
    params.pop('page', None)
    return render(request, 'console/activity.html', {
        'page': page,
        'action': action,
        'actions': AdminAction.ACTIONS,
        'querystring': params.urlencode(),
    })
