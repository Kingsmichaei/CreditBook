from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.contrib.auth import login, logout
from django.contrib.auth import views as auth_views
from django.contrib import messages
from django.db.models import Sum, Count, Q
from django.utils import timezone
from django.http import JsonResponse, HttpResponse
from django.core import signing
from django.core.mail import send_mail
from django.conf import settings
from django.urls import reverse
from datetime import timedelta, date
import csv
import json
import random

from .models import Customer, Sale, Debt, Expense, Income, Staff, Tenant, TenantMembership
from .forms import CustomerForm, SaleForm, DebtForm, ExpenseForm, IncomeForm, StaffForm, RegistrationForm, ProfileForm, EmailOrPhoneAuthenticationForm, normalize_phone


class TenantAwareLoginView(auth_views.LoginView):
    def get_success_url(self):
        redirect_to = self.request.POST.get(self.redirect_field_name, self.request.GET.get(self.redirect_field_name, ''))
        if redirect_to:
            return redirect_to

        if self.request.user.is_authenticated and TenantMembership.objects.filter(user=self.request.user).exists():
            return reverse('dashboard')
        return reverse('register')


def _assign_tenant(instance, request):
    if getattr(request, 'tenant', None) and getattr(instance, 'tenant', None) is None:
        instance.tenant = request.tenant
    return instance


def _tenant_object_or_404(model, request, pk):
    queryset = model.objects.all()
    if getattr(request, 'tenant', None) is not None:
        queryset = queryset.filter(tenant=request.tenant)
    return get_object_or_404(queryset, pk=pk)


def _can_manage_staff(request):
    if getattr(request.user, 'is_superuser', False):
        return True

    tenant = getattr(request, 'tenant', None)
    if tenant is None:
        return False

    return TenantMembership.objects.filter(user=request.user, tenant=tenant, role__in=['owner', 'manager']).exists()


def landing_page(request):
    return render(request, 'core/landing.html')


def about_view(request):
    return render(request, 'core/about.html')


def contact_view(request):
    return render(request, 'core/contact.html')


def privacy_policy_view(request):
    return render(request, 'core/privacy_policy.html')


def terms_of_service_view(request):
    return render(request, 'core/terms_of_service.html')


@login_required
def delete_account(request):
    code_sent = 'delete_account_token' in request.session
    if request.method == 'POST':
        confirm_email = (request.POST.get('confirm_email') or '').strip()
        verification_code = (request.POST.get('verification_code') or '').strip()

        if verification_code:
            token = request.session.get('delete_account_token')
            if not token:
                messages.error(request, 'No verification code was requested. Please confirm your email first.')
                return redirect('delete_account')

            try:
                payload = signing.loads(token, salt='account-delete', max_age=60 * 15)
            except signing.BadSignature:
                messages.error(request, 'The verification code is invalid. Request a new one.')
                request.session.pop('delete_account_token', None)
                return redirect('delete_account')
            except signing.SignatureExpired:
                messages.error(request, 'The verification code has expired. Request a new one.')
                request.session.pop('delete_account_token', None)
                return redirect('delete_account')

            if payload.get('user_id') != request.user.pk:
                messages.error(request, 'This verification code does not match your account.')
                return redirect('delete_account')

            if payload.get('code') != verification_code:
                messages.error(request, 'The verification code is incorrect.')
                return render(request, 'core/delete_account.html', {'code_sent': True})

            user = request.user
            user_email = user.email
            send_mail(
                'Account Deleted Successfully',
                'Your account has been permanently deleted, and all associated data has been removed in accordance with our data retention policy.',
                'We are sorry to see you go. Thank you for using CreditBook. If you decide to return in the future, you are welcome to create a new account at any time.',
                'If you did not request this deletion, please contact our support team immediately.',
                settings.DEFAULT_FROM_EMAIL,
                [user_email],
                fail_silently=False,
            )
            logout(request)
            user.delete()
            request.session.pop('delete_account_token', None)
            messages.success(request, 'Your account was deleted successfully. Thank you for using CreditBook. If you wish to return, you can create a new account at any time.')
            return redirect('landing')

        if confirm_email != request.user.email:
            messages.error(request, 'Please enter the email address on your account to continue.')
            return redirect('delete_account')

        code = f"{random.randint(0, 999999):06d}"
        token = signing.dumps({'user_id': request.user.pk, 'code': code}, salt='account-delete')
        request.session['delete_account_token'] = token
        request.session['delete_account_sent_at'] = timezone.now().isoformat()

        send_mail(
            'Your CreditBook account deletion code',
            f'Your verification code is: {code}\n\nEnter this code on the account deletion page to confirm deleting your account. The code expires in 15 minutes.',
            settings.DEFAULT_FROM_EMAIL,
            [request.user.email],
            fail_silently=False,
        )
        messages.info(request, 'A six-digit verification code was sent to your email. Enter it below to confirm account deletion.')
        return render(request, 'core/delete_account.html', {'code_sent': True})

    return render(request, 'core/delete_account.html', {'code_sent': code_sent})


@login_required
def delete_account_confirm(request, token):
    try:
        payload = signing.loads(token, salt='account-delete', max_age=60 * 60)
    except signing.BadSignature:
        messages.error(request, 'That confirmation link is invalid.')
        return redirect('delete_account')
    except signing.SignatureExpired:
        messages.error(request, 'That confirmation link has expired. Please request a new one.')
        return redirect('delete_account')

    if payload.get('user_id') != request.user.pk:
        messages.error(request, 'That confirmation link does not match your account.')
        return redirect('dashboard')

    user = request.user
    logout(request)
    user.delete()
    messages.success(request, 'Your account was deleted successfully.')
    return redirect('landing')


@login_required
def profile_view(request):
    tenant = getattr(request, 'tenant', None)
    if not tenant:
        return redirect('register')

    if request.method == 'POST':
        form = ProfileForm(request.POST, user=request.user, tenant=tenant)
        if form.is_valid():
            request.user.email = form.cleaned_data['email']
            request.user.username = form.cleaned_data['email']
            request.user.last_name = form.cleaned_data['phone']
            request.user.save()
            tenant.business_name = form.cleaned_data['business_name']
            tenant.currency = form.cleaned_data['currency'] or tenant.currency
            tenant.save()
            messages.success(request, 'Profile updated successfully.')
            return redirect('profile_view')
    else:
        form = ProfileForm(user=request.user, tenant=tenant)

    return render(request, 'core/profile.html', {'form': form, 'tenant': tenant})


def register(request):
    if request.user.is_authenticated and getattr(request, 'tenant', None):
        return redirect('dashboard')

    form = RegistrationForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        email = form.cleaned_data['email']
        username = email
        user = get_user_model().objects.create_user(
            username=username,
            email=email,
            password=form.cleaned_data['password1'],
            first_name=form.cleaned_data['owner_name'],
            last_name=normalize_phone(form.cleaned_data['phone']),
        )
        tenant = Tenant.objects.create(
            owner=user,
            business_name=form.cleaned_data['business_name'],
            trial_ends_at=timezone.now().date() + timedelta(days=14),
            subscription_status='trial',
        )
        TenantMembership.objects.create(user=user, tenant=tenant, role='owner')
        login(request, user)
        messages.success(request, f'Welcome to CreditBook, {tenant.business_name}!')
        return redirect('dashboard')

    return render(request, 'core/register.html', {'form': form})


# ─── Dashboard ────────────────────────────────────────────────────────────────

@login_required
def dashboard(request):
    if not getattr(request, 'tenant', None):
        messages.info(request, 'Create a business workspace to get started.')
        return redirect('register')

    today = timezone.now().date()
    month_start = today.replace(day=1)

    monthly_sales = Sale.objects.filter(date__gte=month_start).aggregate(t=Sum('total'))['t'] or 0
    monthly_expenses = Expense.objects.filter(date__gte=month_start).aggregate(t=Sum('amount'))['t'] or 0
    monthly_income = Income.objects.filter(date__gte=month_start).aggregate(t=Sum('amount'))['t'] or 0

    total_debts = Debt.objects.filter(is_paid=False).aggregate(t=Sum('amount'))['t'] or 0
    total_sales_ever = Sale.objects.aggregate(t=Sum('total'))['t'] or 0

    recent_sales = Sale.objects.select_related('customer').order_by('-date', '-created_at')[:5]
    recent_debts = Debt.objects.filter(is_paid=False).select_related('customer').order_by('-created_at')[:5]
    recent_expenses = Expense.objects.order_by('-date')[:5]
    overdue_debts = Debt.objects.filter(is_paid=False, due_date__lt=today).select_related('customer')

    # Last 7 days sales chart
    chart_labels = []
    chart_sales = []
    chart_expenses = []
    for i in range(6, -1, -1):
        day = today - timedelta(days=i)
        day_sales = Sale.objects.filter(date=day).aggregate(t=Sum('total'))['t'] or 0
        day_expenses = Expense.objects.filter(date=day).aggregate(t=Sum('amount'))['t'] or 0
        chart_labels.append(day.strftime('%a %d'))
        chart_sales.append(float(day_sales))
        chart_expenses.append(float(day_expenses))

    # Last 6 months chart
    monthly_labels = []
    monthly_sales_data = []
    monthly_expense_data = []
    for i in range(5, -1, -1):
        m_date = today.replace(day=1) - timedelta(days=i * 30)
        m_start = m_date.replace(day=1)
        next_month = (m_start.replace(day=28) + timedelta(days=4)).replace(day=1)
        ms = Sale.objects.filter(date__gte=m_start, date__lt=next_month).aggregate(t=Sum('total'))['t'] or 0
        me = Expense.objects.filter(date__gte=m_start, date__lt=next_month).aggregate(t=Sum('amount'))['t'] or 0
        monthly_labels.append(m_start.strftime('%b'))
        monthly_sales_data.append(float(ms))
        monthly_expense_data.append(float(me))

    context = {
        'monthly_sales': monthly_sales,
        'monthly_expenses': monthly_expenses,
        'monthly_income': monthly_income,
        'net_profit': monthly_sales + monthly_income - monthly_expenses,
        'total_debts': total_debts,
        'total_sales_ever': total_sales_ever,
        'recent_sales': recent_sales,
        'recent_debts': recent_debts,
        'recent_expenses': recent_expenses,
        'overdue_debts': overdue_debts,
        'overdue_count': overdue_debts.count(),
        'total_customers': Customer.objects.count(),
        'total_staff': Staff.objects.filter(is_active=True).count(),
        'chart_labels': json.dumps(chart_labels),
        'chart_sales': json.dumps(chart_sales),
        'chart_expenses': json.dumps(chart_expenses),
        'monthly_labels': json.dumps(monthly_labels),
        'monthly_sales_data': json.dumps(monthly_sales_data),
        'monthly_expense_data': json.dumps(monthly_expense_data),
    }
    return render(request, 'core/dashboard.html', context)


# ─── Customers ────────────────────────────────────────────────────────────────

@login_required
def customers_list(request):
    q = request.GET.get('q', '')
    customers = Customer.objects.all()
    if q:
        customers = customers.filter(Q(name__icontains=q) | Q(phone__icontains=q))
    return render(request, 'core/customers_list.html', {'customers': customers, 'q': q})


@login_required
def customer_add(request):
    form = CustomerForm(request.POST or None)
    if form.is_valid():
        customer = _assign_tenant(form.save(commit=False), request)
        customer.save()
        messages.success(request, 'Customer added successfully.')
        return redirect('customers_list')
    return render(request, 'core/customer_form.html', {'form': form, 'title': 'Add Customer'})


@login_required
def customer_edit(request, pk):
    customer = _tenant_object_or_404(Customer, request, pk)
    form = CustomerForm(request.POST or None, instance=customer)
    if form.is_valid():
        customer = _assign_tenant(form.save(commit=False), request)
        customer.save()
        messages.success(request, 'Customer updated.')
        return redirect('customer_detail', pk=pk)
    return render(request, 'core/customer_form.html', {'form': form, 'title': 'Edit Customer', 'customer': customer})


@login_required
def customer_detail(request, pk):
    customer = _tenant_object_or_404(Customer, request, pk)
    sales = customer.sales.order_by('-date')
    debts = customer.debts.order_by('-created_at')
    return render(request, 'core/customer_detail.html', {
        'customer': customer,
        'sales': sales,
        'debts': debts,
    })


@login_required
def customer_delete(request, pk):
    customer = _tenant_object_or_404(Customer, request, pk)
    if request.method == 'POST':
        name = customer.name
        customer.delete()
        messages.success(request, f'Customer "{name}" deleted.')
        return redirect('customers_list')
    return render(request, 'core/confirm_delete.html', {'object': customer, 'type': 'Customer'})


# ─── Sales ────────────────────────────────────────────────────────────────────

@login_required
def sales_list(request):
    q = request.GET.get('q', '')
    sales = Sale.objects.select_related('customer').all()
    if q:
        sales = sales.filter(Q(product__icontains=q) | Q(customer__name__icontains=q))
    total = sales.aggregate(t=Sum('total'))['t'] or 0
    return render(request, 'core/sales_list.html', {'sales': sales, 'q': q, 'total': total})


@login_required
def sales_export(request):
    q = request.GET.get('q', '')
    sales = Sale.objects.select_related('customer').all()
    if q:
        sales = sales.filter(Q(product__icontains=q) | Q(customer__name__icontains=q))

    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="sales.csv"'

    writer = csv.writer(response)
    writer.writerow(['Date', 'Product', 'Customer', 'Quantity', 'Unit Price', 'Total', 'Payment Method', 'Notes'])

    for sale in sales.order_by('-date', '-created_at'):
        writer.writerow([
            sale.date,
            sale.product,
            sale.customer.name if sale.customer else 'Walk-in',
            sale.quantity,
            sale.unit_price,
            sale.total,
            sale.get_payment_method_display(),
            sale.notes,
        ])

    return response


@login_required
def sale_add(request):
    form = SaleForm(request.POST or None)
    if request.POST:
        form = SaleForm(request.POST)
        if form.is_valid():
            sale = _assign_tenant(form.save(commit=False), request)
            sale.save()
            # Auto-create debt if payment is credit
            if sale.payment_method == 'credit' and sale.customer:
                Debt.objects.create(
                    tenant=request.tenant,
                    customer=sale.customer,
                    amount=sale.total,
                    description=f"Credit sale: {sale.product}",
                )
                messages.info(request, 'Debt record auto-created for credit sale.')
            messages.success(request, 'Sale recorded successfully.')
            return redirect('sales_list')
    return render(request, 'core/sale_form.html', {'form': form, 'title': 'Record Sale'})


@login_required
def sale_edit(request, pk):
    sale = _tenant_object_or_404(Sale, request, pk)
    form = SaleForm(request.POST or None, instance=sale)
    if form.is_valid():
        sale = _assign_tenant(form.save(commit=False), request)
        sale.save()
        messages.success(request, 'Sale updated.')
        return redirect('sales_list')
    return render(request, 'core/sale_form.html', {'form': form, 'title': 'Edit Sale', 'sale': sale})


@login_required
def sale_delete(request, pk):
    sale = _tenant_object_or_404(Sale, request, pk)
    if request.method == 'POST':
        sale.delete()
        messages.success(request, 'Sale record deleted.')
        return redirect('sales_list')
    return render(request, 'core/confirm_delete.html', {'object': sale, 'type': 'Sale'})


# ─── Debts ────────────────────────────────────────────────────────────────────

@login_required
def debts_list(request):
    filter_type = request.GET.get('filter', 'unpaid')
    debts = Debt.objects.select_related('customer').all()
    if filter_type == 'unpaid':
        debts = debts.filter(is_paid=False)
    elif filter_type == 'paid':
        debts = debts.filter(is_paid=True)
    elif filter_type == 'overdue':
        debts = debts.filter(is_paid=False, due_date__lt=timezone.now().date())

    total = debts.aggregate(t=Sum('amount'))['t'] or 0
    return render(request, 'core/debts_list.html', {
        'debts': debts,
        'filter_type': filter_type,
        'total': total,
    })


@login_required
def debt_add(request):
    form = DebtForm(request.POST or None)
    if form.is_valid():
        debt = _assign_tenant(form.save(commit=False), request)
        debt.save()
        messages.success(request, 'Debt recorded.')
        return redirect('debts_list')
    return render(request, 'core/debt_form.html', {'form': form, 'title': 'Record Debt'})


@login_required
def debt_edit(request, pk):
    debt = _tenant_object_or_404(Debt, request, pk)
    form = DebtForm(request.POST or None, instance=debt)
    if form.is_valid():
        debt = _assign_tenant(form.save(commit=False), request)
        debt.save()
        messages.success(request, 'Debt updated.')
        return redirect('debts_list')
    return render(request, 'core/debt_form.html', {'form': form, 'title': 'Edit Debt', 'debt': debt})


@login_required
def debt_mark_paid(request, pk):
    debt = _tenant_object_or_404(Debt, request, pk)
    debt.is_paid = True
    debt.paid_date = timezone.now().date()
    debt.save()
    messages.success(request, f'Debt of ₦{debt.amount} for {debt.customer.name} marked as paid.')
    return redirect('debts_list')


@login_required
def debt_delete(request, pk):
    debt = _tenant_object_or_404(Debt, request, pk)
    if request.method == 'POST':
        debt.delete()
        messages.success(request, 'Debt record deleted.')
        return redirect('debts_list')
    return render(request, 'core/confirm_delete.html', {'object': debt, 'type': 'Debt'})


# ─── Expenses ─────────────────────────────────────────────────────────────────

@login_required
def expenses_list(request):
    q = request.GET.get('q', '')
    expenses = Expense.objects.all()
    if q:
        expenses = expenses.filter(Q(description__icontains=q) | Q(category__icontains=q))
    total = expenses.aggregate(t=Sum('amount'))['t'] or 0
    by_category = expenses.values('category').annotate(total=Sum('amount')).order_by('-total')
    return render(request, 'core/expenses_list.html', {
        'expenses': expenses,
        'q': q,
        'total': total,
        'by_category': by_category,
    })


@login_required
def expense_add(request):
    form = ExpenseForm(request.POST or None)
    if form.is_valid():
        expense = _assign_tenant(form.save(commit=False), request)
        expense.save()
        messages.success(request, 'Expense recorded.')
        return redirect('expenses_list')
    return render(request, 'core/expense_form.html', {'form': form, 'title': 'Record Expense'})


@login_required
def expense_edit(request, pk):
    expense = _tenant_object_or_404(Expense, request, pk)
    form = ExpenseForm(request.POST or None, instance=expense)
    if form.is_valid():
        expense = _assign_tenant(form.save(commit=False), request)
        expense.save()
        messages.success(request, 'Expense updated.')
        return redirect('expenses_list')
    return render(request, 'core/expense_form.html', {'form': form, 'title': 'Edit Expense', 'expense': expense})


@login_required
def expense_delete(request, pk):
    expense = _tenant_object_or_404(Expense, request, pk)
    if request.method == 'POST':
        expense.delete()
        messages.success(request, 'Expense deleted.')
        return redirect('expenses_list')
    return render(request, 'core/confirm_delete.html', {'object': expense, 'type': 'Expense'})


# ─── Income ───────────────────────────────────────────────────────────────────

@login_required
def income_list(request):
    income = Income.objects.all()
    total = income.aggregate(t=Sum('amount'))['t'] or 0
    return render(request, 'core/income_list.html', {'income': income, 'total': total})


@login_required
def income_add(request):
    form = IncomeForm(request.POST or None)
    if form.is_valid():
        income = _assign_tenant(form.save(commit=False), request)
        income.save()
        messages.success(request, 'Income recorded.')
        return redirect('income_list')
    return render(request, 'core/income_form.html', {'form': form, 'title': 'Record Income'})


@login_required
def income_edit(request, pk):
    income = _tenant_object_or_404(Income, request, pk)
    form = IncomeForm(request.POST or None, instance=income)
    if form.is_valid():
        income = _assign_tenant(form.save(commit=False), request)
        income.save()
        messages.success(request, 'Income updated.')
        return redirect('income_list')
    return render(request, 'core/income_form.html', {'form': form, 'title': 'Edit Income', 'income': income})


@login_required
def income_delete(request, pk):
    income = _tenant_object_or_404(Income, request, pk)
    if request.method == 'POST':
        income.delete()
        messages.success(request, 'Income record deleted.')
        return redirect('income_list')
    return render(request, 'core/confirm_delete.html', {'object': income, 'type': 'Income'})


# ─── Staff ────────────────────────────────────────────────────────────────────

@login_required
def staff_list(request):
    if not _can_manage_staff(request):
        messages.error(request, 'You do not have permission to access staff management.')
        return redirect('dashboard')
    tenant = getattr(request, 'tenant', None)
    staff_qs = Staff.objects.all()
    if tenant:
        staff_qs = staff_qs.filter(tenant=tenant)
    active_count = staff_qs.filter(is_active=True).count()
    return render(request, 'core/staff_list.html', {
        'staff': staff_qs,
        'active_staff_count': active_count,
    })


@login_required
def staff_add(request):
    if not _can_manage_staff(request):
        messages.error(request, 'You do not have permission to access staff management.')
        return redirect('dashboard')
    form = StaffForm(request.POST or None)
    if form.is_valid():
        staff = _assign_tenant(form.save(commit=False), request)
        user_model = get_user_model()
        user = None
        normalized_phone = normalize_phone(form.cleaned_data.get('phone') or '')

        if staff.user:
            user = staff.user
        else:
            user = user_model.objects.create_user(
                username=form.cleaned_data['email'],
                email=form.cleaned_data['email'],
                password=form.cleaned_data['password'] or 'changeme123',
                is_staff=True,
                is_active=staff.is_active,
                last_name=normalized_phone,
            )

        if form.cleaned_data.get('password'):
            user.set_password(form.cleaned_data['password'])
        user.email = staff.email or ''
        user.is_active = staff.is_active
        user.is_staff = True
        user.last_name = normalized_phone
        user.save()

        staff.user = user
        staff.save()
        TenantMembership.objects.get_or_create(user=user, tenant=request.tenant, defaults={'role': 'staff'})
        messages.success(request, 'Staff member added and can now sign in.')
        return redirect('staff_list')
    return render(request, 'core/staff_form.html', {'form': form, 'title': 'Add Staff Member'})


@login_required
def staff_edit(request, pk):
    if not _can_manage_staff(request):
        messages.error(request, 'You do not have permission to access staff management.')
        return redirect('dashboard')
    staff = _tenant_object_or_404(Staff, request, pk)
    form = StaffForm(request.POST or None, instance=staff)
    if form.is_valid():
        staff = _assign_tenant(form.save(commit=False), request)
        user_model = get_user_model()
        if staff.user is None:
            normalized_phone = normalize_phone(form.cleaned_data.get('phone') or '')
            user = user_model.objects.create_user(
                username=form.cleaned_data['email'],
                email=form.cleaned_data['email'],
                password=form.cleaned_data['password'] or 'changeme123',
                is_staff=True,
                is_active=staff.is_active,
                last_name=normalized_phone,
            )
            staff.user = user
        else:
            normalized_phone = normalize_phone(form.cleaned_data.get('phone') or '')
            user = staff.user
            user.username = form.cleaned_data['email']
            user.email = form.cleaned_data['email']
            user.is_active = staff.is_active
            user.is_staff = True
            user.last_name = normalized_phone
            if form.cleaned_data.get('password'):
                user.set_password(form.cleaned_data['password'])
            user.save()

        if not form.cleaned_data.get('password') and staff.user is not None:
            staff.user.is_active = staff.is_active
            staff.user.is_staff = True
            staff.user.email = form.cleaned_data['email']
            staff.user.username = form.cleaned_data['email']
            staff.user.last_name = normalize_phone(form.cleaned_data.get('phone') or '')
            staff.user.save()

        staff.save()
        TenantMembership.objects.get_or_create(user=user, tenant=request.tenant, defaults={'role': 'staff'})
        messages.success(request, 'Staff record updated.')
        return redirect('staff_list')
    return render(request, 'core/staff_form.html', {'form': form, 'title': 'Edit Staff', 'staff_obj': staff})


@login_required
def staff_delete(request, pk):
    if not _can_manage_staff(request):
        messages.error(request, 'You do not have permission to access staff management.')
        return redirect('dashboard')
    staff = _tenant_object_or_404(Staff, request, pk)
    if request.method == 'POST':
        name = staff.name
        staff.delete()
        messages.success(request, f'Staff member "{name}" removed.')
        return redirect('staff_list')
    return render(request, 'core/confirm_delete.html', {'object': staff, 'type': 'Staff Member'})
