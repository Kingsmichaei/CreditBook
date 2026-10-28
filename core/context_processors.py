from django.db.models import Sum
from django.utils import timezone
from .models import Sale, Expense, Debt, Customer, Staff, TenantMembership


ROLE_LABELS = {'owner': 'Owner', 'manager': 'Manager', 'staff': 'Team member'}


def business_stats(request):
    """Global context for all templates."""
    tenant = getattr(request, 'tenant', None)
    today = timezone.now().date()
    month_start = today.replace(day=1)

    show_tenant_admin_links = False
    current_role_label = ''
    if request.user.is_authenticated and tenant is not None:
        membership = TenantMembership.objects.filter(user=request.user, tenant=tenant).first()
        if membership is not None:
            current_role_label = ROLE_LABELS.get(membership.role, membership.get_role_display())
        elif request.user.is_superuser:
            current_role_label = 'Platform admin'
        show_tenant_admin_links = (
            request.user.is_superuser or
            (membership is not None and membership.role in ['owner', 'manager'])
        )

    sales = Sale.objects.filter(date__gte=month_start)
    expenses = Expense.objects.filter(date__gte=month_start)
    debts = Debt.objects.filter(is_paid=False)
    staff = Staff.objects.filter(is_active=True)
    customers = Customer.objects.all()

    if tenant is not None:
        sales = sales.filter(tenant=tenant)
        expenses = expenses.filter(tenant=tenant)
        debts = debts.filter(tenant=tenant)
        staff = staff.filter(tenant=tenant)
        customers = customers.filter(tenant=tenant)

    monthly_sales = sales.aggregate(t=Sum('total'))['t'] or 0
    monthly_expenses = expenses.aggregate(t=Sum('amount'))['t'] or 0
    total_unpaid_debts = debts.aggregate(t=Sum('amount'))['t'] or 0

    return {
        'business_name': tenant.business_name if tenant else 'CreditBook',
        'business_currency': tenant.currency if tenant else '₦',
        'monthly_sales': monthly_sales,
        'monthly_expenses': monthly_expenses,
        'total_unpaid_debts': total_unpaid_debts,
        'net_monthly': monthly_sales - monthly_expenses,
        'overdue_debts_count': debts.filter(due_date__lt=today).count(),
        'active_staff_count': staff.count(),
        'customers_count': customers.count(),
        'show_tenant_admin_links': show_tenant_admin_links,
        'current_role_label': current_role_label,
    }
