"""Celery tasks for recurring billing and trial expiry automation."""
import logging
from datetime import date, timedelta
from decimal import Decimal
from uuid import uuid4

try:
    from celery import shared_task
except ImportError:  # pragma: no cover - fallback when Celery is unavailable
    def shared_task(*args, **kwargs):
        def decorator(func):
            return func
        return decorator

from django.conf import settings
from django.utils import timezone

from core.models import Tenant
from .emails import (
    send_account_suspended,
    send_payment_failed,
    send_payment_success,
    send_second_failed,
    send_trial_expired,
)
from .models import BillingLog
from .services.nomba import NombaAPIError, NombaService

logger = logging.getLogger(__name__)


def handle_failed_charge(tenant):
    """Update subscription state after a failed recurring charge."""
    tenant.failed_payment_count += 1
    tenant.last_payment_attempt = timezone.now()
    if tenant.failed_payment_count == 1:
        tenant.next_billing_date = timezone.now().date() + timedelta(days=3)
        send_payment_failed(tenant, 1, tenant.next_billing_date)
    elif tenant.failed_payment_count == 2:
        tenant.next_billing_date = timezone.now().date() + timedelta(days=3)
        send_second_failed(tenant, 2, tenant.next_billing_date)
    else:
        tenant.subscription_status = 'suspended'
        tenant.next_billing_date = timezone.now().date()
        send_account_suspended(tenant)
    tenant.save(update_fields=['failed_payment_count', 'last_payment_attempt', 'next_billing_date', 'subscription_status'])


@shared_task
def expire_trials():
    """Expire trial plans for tenants that have exhausted their trial period."""
    today = timezone.now().date()
    tenants = Tenant.objects.filter(trial_ends_at__lt=today, subscription_status='trial', nomba_token_key='')
    for tenant in tenants:
        tenant.subscription_status = 'read_only'
        tenant.save(update_fields=['subscription_status'])
        send_trial_expired(tenant)


@shared_task
def charge_due_subscriptions():
    """Queue recurring charges for tenants whose billing date has arrived."""
    today = timezone.now().date()
    tenants = Tenant.objects.filter(next_billing_date__lte=today, subscription_status__in=['active', 'read_only', 'past_due'], nomba_token_key__gt='')
    for tenant in tenants:
        process_tenant_charge.delay(tenant.id)


@shared_task
def send_trial_ending_reminders():
    """Send reminder emails for tenants whose trial is ending in three days."""
    today = timezone.now().date()
    tenants = Tenant.objects.filter(subscription_status='trial', trial_ends_at__lte=today + timedelta(days=3), trial_ends_at__gt=today, nomba_token_key='')
    for tenant in tenants:
        from .emails import send_trial_ending_reminder
        send_trial_ending_reminder(tenant)


@shared_task(bind=True, max_retries=0)
def process_tenant_charge(self, tenant_id):
    """Process a single tenant payment charge."""
    tenant = Tenant.objects.get(pk=tenant_id)
    order_ref = str(uuid4())
    subscription_amount = Decimal(settings.SUBSCRIPTION_PRICE_NGN)
    billing_log = BillingLog.objects.create(
        tenant=tenant,
        order_reference=order_ref,
        amount=subscription_amount,
        status='pending',
        is_tokenized=True,
    )
    service = NombaService()
    try:
        success, response = service.charge_tokenized_card(tenant, settings.SUBSCRIPTION_PRICE_NGN, order_ref)
    except NombaAPIError as exc:
        billing_log.status = 'failed'
        billing_log.failure_reason = exc.description
        billing_log.raw_response = {'error': exc.description, 'code': exc.code}
        billing_log.save(update_fields=['status', 'failure_reason', 'raw_response'])
        handle_failed_charge(tenant)
        return

    if success:
        try:
            verified, data = service.verify_transaction(order_ref)
        except NombaAPIError:
            verified = False
            data = {}

        if verified:
            billing_log.status = 'success'
            billing_log.nomba_txn_id = data.get('id', '') or data.get('transactionId', '')
            billing_log.raw_response = data
            billing_log.save(update_fields=['status', 'nomba_txn_id', 'raw_response'])
            if tenant.subscription_status in ['trial', 'read_only', 'past_due', 'paused', 'suspended', 'cancelled']:
                tenant.subscription_status = 'active'
            tenant.next_billing_date = timezone.now().date() + timedelta(days=30)
            tenant.failed_payment_count = 0
            tenant.subscription_start = tenant.subscription_start or timezone.now().date()
            tenant.save(update_fields=['subscription_status', 'next_billing_date', 'failed_payment_count', 'subscription_start'])
            send_payment_success(tenant, settings.SUBSCRIPTION_PRICE_NGN, tenant.next_billing_date)
            return

        billing_log.status = 'failed'
        billing_log.failure_reason = 'Verification failed'
        billing_log.raw_response = {'verification': 'failed'}
        billing_log.save(update_fields=['status', 'failure_reason', 'raw_response'])
        handle_failed_charge(tenant)
        return
