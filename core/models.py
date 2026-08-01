from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.db.models import Sum
from django.utils.text import slugify
from threading import local

_tenant_ctx = local()


def set_current_tenant(tenant):
    setattr(_tenant_ctx, 'tenant', tenant)


def get_current_tenant():
    return getattr(_tenant_ctx, 'tenant', None)


def clear_current_tenant():
    if hasattr(_tenant_ctx, 'tenant'):
        delattr(_tenant_ctx, 'tenant')


class Tenant(models.Model):
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='owned_tenants')
    business_name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=120, unique=True, blank=True)
    currency = models.CharField(max_length=10, default='₦')
    created_at = models.DateTimeField(auto_now_add=True)
    trial_ends_at = models.DateField(null=True, blank=True)
    nomba_token_key = models.CharField(max_length=200, blank=True)
    nomba_card_type = models.CharField(max_length=50, blank=True)
    nomba_card_pan = models.CharField(max_length=50, blank=True)
    subscription_status = models.CharField(
        max_length=20,
        choices=[
            ('trial', 'Trial'),
            ('active', 'Active'),
            ('read_only', 'Read Only'),
            ('paused', 'Paused'),
            ('cancelled', 'Cancelled'),
        ],
        default='trial',
    )
    subscription_start = models.DateField(null=True, blank=True)
    next_billing_date = models.DateField(null=True, blank=True)
    failed_payment_count = models.IntegerField(default=0)
    last_payment_attempt = models.DateTimeField(null=True, blank=True)

    def trial_days_left(self):
        if not self.trial_ends_at:
            return None
        return max((self.trial_ends_at - timezone.now().date()).days, 0)

    def is_trial_warning(self):
        days_left = self.trial_days_left()
        return self.subscription_status == 'trial' and days_left is not None and 0 < days_left <= 3

    def is_read_only(self):
        return self.subscription_status in ['read_only', 'past_due']

    def is_paused(self):
        return self.subscription_status in ['paused', 'suspended']

    def is_active(self):
        return self.subscription_status == 'active'

    def update_subscription_state(self):
        if self.subscription_status in ['active', 'cancelled']:
            return
        if not self.trial_ends_at:
            return

        today = timezone.now().date()
        days_since_end = (today - self.trial_ends_at).days
        new_status = self.subscription_status

        if days_since_end >= 7:
            new_status = 'paused'
        elif days_since_end >= 0:
            new_status = 'read_only'
        else:
            new_status = 'trial'

        if new_status != self.subscription_status:
            self.subscription_status = new_status
            self.save(update_fields=['subscription_status'])

    def save(self, *args, **kwargs):
        if not self.slug:
            base_slug = slugify(self.business_name) or 'tenant'
            slug = base_slug
            suffix = 1
            while Tenant.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug = f'{base_slug}-{suffix}'
                suffix += 1
            self.slug = slug
        super().save(*args, **kwargs)

    def __str__(self):
        return self.business_name


class TenantMembership(models.Model):
    ROLE_CHOICES = [('owner', 'Owner'), ('manager', 'Manager'), ('staff', 'Staff')]
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='tenant_memberships')
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='memberships')
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='staff')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('user', 'tenant')

    def __str__(self):
        return f'{self.user} @ {self.tenant}'


class TenantManager(models.Manager):
    def get_queryset(self):
        tenant = get_current_tenant()
        queryset = super().get_queryset()
        if tenant is not None:
            return queryset.filter(tenant=tenant)
        return queryset


class Staff(models.Model):
    ROLE_CHOICES = [
        ('owner', 'Owner'),
        ('manager', 'Manager'),
        ('cashier', 'Cashier'),
        ('salesperson', 'Sales Person'),
        ('accountant', 'Accountant'),
        ('other', 'Other'),
    ]
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='staff_members', null=True, blank=True)
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='staff_profile')
    name = models.CharField(max_length=200)
    role = models.CharField(max_length=50, choices=ROLE_CHOICES, default='other')
    phone = models.CharField(max_length=20, blank=True)
    email = models.EmailField(blank=True)
    address = models.TextField(blank=True)
    salary = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    is_active = models.BooleanField(default=True)
    date_joined = models.DateField(default=timezone.now)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = TenantManager()

    class Meta:
        ordering = ['name']
        verbose_name_plural = 'Staff'

    def __str__(self):
        return f"{self.name} ({self.get_role_display()})"


class Customer(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='customers', null=True, blank=True)
    name = models.CharField(max_length=200)
    phone = models.CharField(max_length=20, blank=True)
    email = models.EmailField(blank=True)
    address = models.TextField(blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = TenantManager()

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name

    @property
    def total_debt(self):
        result = self.debts.filter(is_paid=False).aggregate(total=Sum('amount'))
        return result['total'] or 0

    @property
    def total_purchases(self):
        result = self.sales.aggregate(total=Sum('total'))
        return result['total'] or 0

    @property
    def whatsapp_number(self):
        phone = self.phone.strip().replace(' ', '').replace('-', '').replace('(', '').replace(')', '')
        if phone.startswith('0'):
            phone = '234' + phone[1:]
        elif phone.startswith('+'):
            phone = phone[1:]
        return phone


class Sale(models.Model):
    PAYMENT_CHOICES = [
        ('cash', 'Cash'),
        ('transfer', 'Bank Transfer'),
        ('pos', 'POS/Card'),
        ('credit', 'Credit (Debt)'),
    ]
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='sales', null=True, blank=True)
    customer = models.ForeignKey(Customer, on_delete=models.SET_NULL, null=True, blank=True, related_name='sales')
    product = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    quantity = models.DecimalField(max_digits=10, decimal_places=2, default=1)
    unit_price = models.DecimalField(max_digits=12, decimal_places=2)
    total = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    payment_method = models.CharField(max_length=20, choices=PAYMENT_CHOICES, default='cash')
    date = models.DateField(default=timezone.now)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = TenantManager()

    class Meta:
        ordering = ['-date', '-created_at']

    def save(self, *args, **kwargs):
        self.total = self.quantity * self.unit_price
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.product} — ₦{self.total} ({self.date})"


class Debt(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='debts', null=True, blank=True)
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name='debts')
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    description = models.TextField(blank=True)
    due_date = models.DateField(null=True, blank=True)
    is_paid = models.BooleanField(default=False)
    paid_date = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = TenantManager()

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        status = "PAID" if self.is_paid else "UNPAID"
        return f"{self.customer.name} — ₦{self.amount} [{status}]"

    @property
    def is_overdue(self):
        if self.due_date and not self.is_paid:
            return self.due_date < timezone.now().date()
        return False


class Expense(models.Model):
    CATEGORY_CHOICES = [
        ('rent', 'Rent'),
        ('utilities', 'Utilities/Bills'),
        ('salary', 'Staff Salary'),
        ('stock', 'Stock / Inventory'),
        ('transport', 'Transport / Logistics'),
        ('marketing', 'Marketing / Adverts'),
        ('maintenance', 'Maintenance / Repairs'),
        ('equipment', 'Equipment'),
        ('tax', 'Tax / Government'),
        ('other', 'Other'),
    ]
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='expenses', null=True, blank=True)
    category = models.CharField(max_length=50, choices=CATEGORY_CHOICES, default='other')
    description = models.CharField(max_length=300)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    date = models.DateField(default=timezone.now)
    receipt_note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = TenantManager()

    class Meta:
        ordering = ['-date', '-created_at']

    def __str__(self):
        return f"{self.get_category_display()} — ₦{self.amount} ({self.date})"


class Income(models.Model):
    CATEGORY_CHOICES = [
        ('sales', 'Sales Revenue'),
        ('investment', 'Investment'),
        ('loan', 'Loan Received'),
        ('refund', 'Refund / Return'),
        ('other', 'Other Income'),
    ]
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='income', null=True, blank=True)
    description = models.CharField(max_length=300)
    category = models.CharField(max_length=50, choices=CATEGORY_CHOICES, default='sales')
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    date = models.DateField(default=timezone.now)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = TenantManager()

    class Meta:
        ordering = ['-date', '-created_at']

    def __str__(self):
        return f"{self.description} — ₦{self.amount} ({self.date})"
