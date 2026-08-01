"""Email helpers for billing lifecycle notifications."""
import logging
from datetime import date
from pathlib import Path

from django.conf import settings
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.utils import timezone

logger = logging.getLogger(__name__)


def _send_html_email(subject: str, template_name: str, context: dict, recipient: str) -> None:
    """Send an HTML email using a template file."""
    html_message = render_to_string(template_name, context)
    send_mail(subject, '', settings.DEFAULT_FROM_EMAIL, [recipient], html_message=html_message, fail_silently=False)


def send_trial_ending_reminder(tenant) -> None:
    """Send a reminder email when a tenant's trial is ending soon."""
    logger.info('Sending trial reminder to tenant %s', tenant.id)
    _send_html_email(
        'Your trial is ending soon',
        'billing/emails/trial_ending_reminder.html',
        {'tenant': tenant},
        tenant.owner.email,
    )


def send_trial_expired(tenant) -> None:
    """Send an email when a trial expires without a payment method."""
    logger.info('Sending trial expired email to tenant %s', tenant.id)
    _send_html_email(
        'Your trial has expired',
        'billing/emails/trial_expired.html',
        {'tenant': tenant},
        tenant.owner.email,
    )


def send_payment_success(tenant, amount, next_billing_date) -> None:
    """Send an email after a successful recurring payment."""
    logger.info('Sending payment success email to tenant %s', tenant.id)
    _send_html_email(
        'Payment successful',
        'billing/emails/payment_success.html',
        {'tenant': tenant, 'amount': amount, 'next_billing_date': next_billing_date},
        tenant.owner.email,
    )


def send_payment_failed(tenant, attempt_number, next_retry_date) -> None:
    """Send a reminder email after the first failed payment."""
    logger.info('Sending payment failed email to tenant %s', tenant.id)
    _send_html_email(
        'Payment failed',
        'billing/emails/payment_failed.html',
        {'tenant': tenant, 'attempt_number': attempt_number, 'next_retry_date': next_retry_date},
        tenant.owner.email,
    )


def send_second_failed(tenant, attempt_number, next_retry_date) -> None:
    """Send an email after a second failed payment."""
    logger.info('Sending second payment failure email to tenant %s', tenant.id)
    _send_html_email(
        'Payment failed again',
        'billing/emails/second_failed.html',
        {'tenant': tenant, 'attempt_number': attempt_number, 'next_retry_date': next_retry_date},
        tenant.owner.email,
    )


def send_account_suspended(tenant) -> None:
    """Notify a tenant that their account has been suspended."""
    logger.info('Sending account suspension email to tenant %s', tenant.id)
    _send_html_email(
        'Your account has been suspended',
        'billing/emails/account_suspended.html',
        {'tenant': tenant},
        tenant.owner.email,
    )
