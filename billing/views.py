"""Views for billing and subscription management."""
import logging
from decimal import Decimal
from uuid import uuid4

from datetime import timedelta

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.http import HttpResponse

from core.models import Tenant
from .models import BillingLog
from .services.nomba import NombaAPIError, NombaService
from .tasks import handle_failed_charge

logger = logging.getLogger(__name__)


def _get_tenant_from_request(request):
    """Return the current tenant for the authenticated user."""
    return getattr(request, 'tenant', None)


def _mask_pan(pan: str) -> str:
    """Mask a card PAN while preserving its last four digits."""
    if not pan:
        return ''
    if len(pan) <= 4:
        return pan
    return f"{pan[:4]}***{pan[-4:]}"

def _mark_billing_log_failed(billing_log, reason: str, raw_response: dict):
    if not billing_log:
        return
    billing_log.status = 'failed'
    billing_log.failure_reason = reason
    billing_log.raw_response = raw_response
    billing_log.save(update_fields=['status', 'failure_reason', 'raw_response'])


@login_required
def billing_dashboard_view(request):
    """Render the billing dashboard for the current tenant."""
    tenant = _get_tenant_from_request(request)
    if not tenant:
        return redirect('register')
    logs = BillingLog.objects.filter(tenant=tenant, status='success').order_by('-created_at')[:10]
    return render(request, 'billing/dashboard.html', {
        'tenant': tenant,
        'logs': logs,
        'masked_pan': _mask_pan(tenant.nomba_card_pan),
        'subscription_price': settings.SUBSCRIPTION_PRICE_NGN,
    })


@login_required
def subscribe_view(request):
    """Create a Nomba checkout order and redirect the tenant to checkout."""
    tenant = _get_tenant_from_request(request)
    if not tenant:
        return redirect('register')
    if tenant.subscription_status == 'active':
        return redirect('billing_dashboard')

    if request.method == 'POST':
        order_ref = str(uuid4())
        service = NombaService()
        try:
            checkout_link = service.create_checkout_order(tenant, settings.SUBSCRIPTION_PRICE_NGN, order_ref)
        except NombaAPIError as exc:
            messages.error(request, f'Payment setup is currently unavailable: {exc.description}')
            return render(request, 'billing/subscribe.html', {
                'tenant': tenant,
                'subscription_price': settings.SUBSCRIPTION_PRICE_NGN,
                'error_message': exc.description,
            })

        BillingLog.objects.create(
            tenant=tenant,
            order_reference=order_ref,
            amount=Decimal(settings.SUBSCRIPTION_PRICE_NGN),
            status='pending',
            is_tokenized=True,
        )
        return redirect(checkout_link)

    return render(request, 'billing/subscribe.html', {
        'tenant': tenant,
        'subscription_price': settings.SUBSCRIPTION_PRICE_NGN,
    })


@login_required
def payment_callback_view(request):
    """Verify payment status and reconcile the local DB after checkout."""
    tenant = _get_tenant_from_request(request)
    order_reference = request.GET.get('orderReference')
    if order_reference:
        service = NombaService()
        try:
            verified, data = service.verify_transaction(order_reference)
        except NombaAPIError as exc:
            messages.error(request, exc.description)
            return redirect('billing_dashboard')

        billing_log = BillingLog.objects.filter(order_reference=order_reference, tenant=tenant).first()
        token_key = data.get('tokenKey') or (data.get('tokenizedCardData', {}) or {}).get('tokenKey')
        tokenized_card = data.get('tokenizedCardData', {}) or {}
        card_type = tokenized_card.get('cardType') or data.get('cardType', '') or data.get('paymentMethod', '')
        card_pan = tokenized_card.get('cardPan') or data.get('cardPan', '') or data.get('pan', '')

        if verified:
            with transaction.atomic():
                if token_key and token_key != 'N/A':
                    tenant.nomba_token_key = token_key
                    tenant.nomba_card_type = card_type or tenant.nomba_card_type
                    tenant.nomba_card_pan = card_pan or tenant.nomba_card_pan
                if tenant.subscription_status in ['trial', 'read_only', 'past_due', 'paused']:
                    tenant.subscription_status = 'active'
                tenant.next_billing_date = timezone.now().date() + timedelta(days=30)
                tenant.subscription_start = tenant.subscription_start or timezone.now().date()
                tenant.failed_payment_count = 0
                tenant.last_payment_attempt = timezone.now()
                tenant.save(update_fields=[
                    'nomba_token_key', 'nomba_card_type', 'nomba_card_pan',
                    'subscription_status', 'next_billing_date', 'subscription_start',
                    'failed_payment_count', 'last_payment_attempt'
                ])
                if billing_log:
                    billing_log.status = 'success'
                    billing_log.nomba_txn_id = data.get('transactionId') or data.get('id', '')
                    billing_log.raw_response = data
                    billing_log.save(update_fields=['status', 'nomba_txn_id', 'raw_response'])

            messages.success(request, 'Your payment was confirmed and your subscription is now active.')
        else:
            status = (data.get('status') or '').upper()
            if status in ['FAILED', 'DECLINED', 'ERROR', 'CANCELLED', 'CANCELED']:
                with transaction.atomic():
                    _mark_billing_log_failed(
                        billing_log,
                        data.get('message', 'Payment failed or was cancelled during verification.'),
                        data,
                    )
                    handle_failed_charge(tenant)
                messages.error(request, 'Your payment was cancelled or failed and will not remain pending.')
            else:
                if billing_log:
                    billing_log.raw_response = data
                    billing_log.save(update_fields=['raw_response'])
                messages.warning(request, 'Your payment is still pending. Please refresh this page after a few moments.')

    return render(request, 'billing/dashboard.html', {
        'tenant': tenant,
        'logs': BillingLog.objects.filter(tenant=tenant, status='success').order_by('-created_at')[:10],
        'masked_pan': _mask_pan(tenant.nomba_card_pan),
        'subscription_price': settings.SUBSCRIPTION_PRICE_NGN,
    })


@csrf_exempt
def nomba_webhook_view(request):
    """Receive and process Nomba webhook events idempotently."""
    if request.method != 'POST':
        return HttpResponse(status=405)

    import base64
    import hashlib
    import hmac
    import json

    payload = json.loads(request.body.decode('utf-8'))
    headers = {
        'nomba-signature': request.headers.get('nomba-signature', ''),
        'nomba-signature-algorithm': request.headers.get('nomba-signature-algorithm', ''),
        'nomba-timestamp': request.headers.get('nomba-timestamp', ''),
    }

    def verify_nomba_signature(payload_dict, headers_dict, secret):
        data = payload_dict.get('data', {})
        transaction = data.get('transaction', {})
        merchant = data.get('merchant', {})
        string_to_sign = ':'.join([
            payload_dict.get('event_type', ''),
            payload_dict.get('requestId', ''),
            merchant.get('userId', ''),
            merchant.get('walletId', ''),
            transaction.get('transactionId', ''),
            transaction.get('type', ''),
            transaction.get('time', ''),
            transaction.get('responseCode', '') or '',
            headers_dict.get('nomba-timestamp', ''),
        ])
        computed = base64.b64encode(hmac.new(secret.encode(), string_to_sign.encode(), hashlib.sha256).digest()).decode()
        return hmac.compare_digest(computed, headers_dict.get('nomba-signature', ''))

    if not verify_nomba_signature(payload, headers, settings.NOMBA_WEBHOOK_SECRET):
        logger.warning('Invalid Nomba webhook signature for request %s', payload.get('requestId'))
        return HttpResponse(status=400)

    event_type = payload.get('event_type')
    data = payload.get('data', {})
    order_data = data.get('order', {})
    tenant_id = order_data.get('customerId')
    order_reference = order_data.get('orderReference')
    if not tenant_id or not order_reference:
        return HttpResponse(status=200)

    tenant = Tenant.objects.filter(pk=tenant_id).first()
    if not tenant:
        return HttpResponse(status=200)

    if event_type == 'payment_success':
        tokenized_card = data.get('tokenizedCardData', {}) or {}
        token_key = tokenized_card.get('tokenKey') or data.get('tokenKey')
        card_type = tokenized_card.get('cardType') or data.get('cardType', '') or data.get('paymentMethod', '')
        card_pan = tokenized_card.get('cardPan') or data.get('cardPan', '') or data.get('pan', '')
        with transaction.atomic():
            if token_key and token_key != 'N/A':
                tenant.nomba_token_key = token_key
                tenant.nomba_card_type = card_type
                tenant.nomba_card_pan = card_pan
            if tenant.subscription_status in ['trial', 'read_only', 'past_due', 'paused']:
                tenant.subscription_status = 'active'
            tenant.next_billing_date = timezone.now().date() + timedelta(days=30)
            tenant.subscription_start = tenant.subscription_start or timezone.now().date()
            tenant.failed_payment_count = 0
            tenant.save(update_fields=['nomba_token_key', 'nomba_card_type', 'nomba_card_pan', 'subscription_status', 'next_billing_date', 'subscription_start', 'failed_payment_count'])
            BillingLog.objects.filter(order_reference=order_reference).update(status='success')
        return HttpResponse(status=200)

    if event_type == 'payment_failed':
        with transaction.atomic():
            handle_failed_charge(tenant)
            BillingLog.objects.filter(order_reference=order_reference).update(status='failed')
        return HttpResponse(status=200)

    return HttpResponse(status=200)


@login_required
def account_suspended_view(request):
    """Render the suspended account page."""
    tenant = _get_tenant_from_request(request)
    return render(request, 'billing/suspended.html', {
        'tenant': tenant,
        'subscription_price': settings.SUBSCRIPTION_PRICE_NGN,
    })


@login_required
def account_paused_view(request):
    """Render the paused account page."""
    tenant = _get_tenant_from_request(request)
    return render(request, 'billing/paused.html', {
        'tenant': tenant,
        'subscription_price': settings.SUBSCRIPTION_PRICE_NGN,
    })
