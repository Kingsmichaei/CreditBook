"""State transitions the platform owner can apply to a tenant. Each one is audited."""
from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

from django.db import transaction
from django.utils import timezone

from billing.models import BillingLog
from core.models import Tenant

from .models import AdminAction


def _log(tenant, actor, action, previous_status, note='', **metadata):
    return AdminAction.objects.create(
        tenant=tenant,
        tenant_name=tenant.business_name,
        actor=actor,
        action=action,
        previous_status=previous_status,
        new_status=tenant.subscription_status,
        note=note,
        metadata=metadata,
    )


@transaction.atomic
def activate_subscription(tenant, actor, days=30, amount=None, reference='', note=''):
    """Mark a tenant as subscribed for `days`, optionally recording an offline payment."""
    tenant = Tenant.objects.select_for_update().get(pk=tenant.pk)
    previous_status = tenant.subscription_status
    today = timezone.now().date()

    tenant.subscription_status = 'active'
    tenant.subscription_start = tenant.subscription_start or today
    tenant.next_billing_date = today + timedelta(days=days)
    tenant.failed_payment_count = 0
    tenant.save(update_fields=['subscription_status', 'subscription_start', 'next_billing_date', 'failed_payment_count'])

    billing_log_id = None
    if amount:
        billing_log = BillingLog.objects.create(
            tenant=tenant,
            order_reference=f'manual-{uuid4()}',
            amount=Decimal(amount),
            status='success',
            payment_method='manual',
            nomba_txn_id=reference,
            raw_response={'source': 'owner_console', 'reference': reference, 'recorded_by': actor.pk},
        )
        billing_log_id = billing_log.pk

    _log(tenant, actor, 'activate', previous_status, note, days=days,
         amount=str(amount) if amount else None, reference=reference, billing_log_id=billing_log_id)
    return tenant


@transaction.atomic
def terminate_subscription(tenant, actor, reason, remove_card=True):
    """End a tenant's subscription.

    Recurring charges only target active/read-only/past-due tenants, so billing stops either way;
    removing the card additionally guarantees it can never be charged again.
    """
    tenant = Tenant.objects.select_for_update().get(pk=tenant.pk)
    previous_status = tenant.subscription_status

    tenant.subscription_status = 'cancelled'
    tenant.next_billing_date = None
    tenant.failed_payment_count = 0
    fields = ['subscription_status', 'next_billing_date', 'failed_payment_count']
    if remove_card:
        tenant.nomba_token_key = ''
        tenant.nomba_card_type = ''
        tenant.nomba_card_pan = ''
        fields += ['nomba_token_key', 'nomba_card_type', 'nomba_card_pan']
    tenant.save(update_fields=fields)

    _log(tenant, actor, 'terminate', previous_status, reason, card_removed=remove_card)
    return tenant


@transaction.atomic
def extend_trial(tenant, actor, days, note=''):
    """Push the trial end date out by `days`, counting from today or the current end date, whichever is later."""
    tenant = Tenant.objects.select_for_update().get(pk=tenant.pk)
    previous_status = tenant.subscription_status
    today = timezone.now().date()
    base = max(tenant.trial_ends_at or today, today)

    tenant.trial_ends_at = base + timedelta(days=days)
    tenant.subscription_status = 'trial'
    tenant.save(update_fields=['trial_ends_at', 'subscription_status'])

    _log(tenant, actor, 'extend_trial', previous_status, note, days=days, trial_ends_at=tenant.trial_ends_at.isoformat())
    return tenant


@transaction.atomic
def set_disabled(tenant, actor, disabled, reason=''):
    """Turn platform access off or on for every member of a tenant, without touching its subscription."""
    tenant = Tenant.objects.select_for_update().get(pk=tenant.pk)
    tenant.is_disabled = disabled
    tenant.disabled_at = timezone.now() if disabled else None
    tenant.disabled_reason = reason if disabled else ''
    tenant.save(update_fields=['is_disabled', 'disabled_at', 'disabled_reason'])

    _log(tenant, actor, 'disable' if disabled else 'enable', tenant.subscription_status, reason)
    return tenant
