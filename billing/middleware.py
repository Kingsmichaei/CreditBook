"""Middleware for enforcing subscription status access rules."""
import logging
from django.contrib import messages
from django.shortcuts import redirect
from django.utils import timezone

from core.models import TenantMembership

logger = logging.getLogger(__name__)


class SubscriptionMiddleware:
    """Enforce tenant subscription lifecycle, including trial warnings, read-only and paused access."""

    SAFE_READ_ONLY_METHODS = ('GET', 'HEAD', 'OPTIONS')
    BILLING_PATHS = ('/billing/', '/billing/webhook/', '/logout/', '/admin/', '/console/')
    # Console/admin views enforce their own superuser checks, so they stay reachable for the platform owner.
    DISABLED_ALLOWED_PATHS = ('/billing/disabled/', '/logout/', '/admin/', '/console/')

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not request.user.is_authenticated:
            return self.get_response(request)

        tenant = getattr(request, 'tenant', None)
        if not tenant:
            membership = TenantMembership.objects.filter(user=request.user).order_by('created_at').first()
            tenant = membership.tenant if membership else None
            if not tenant:
                return self.get_response(request)

        if tenant.is_disabled:
            if not any(request.path.startswith(path) for path in self.DISABLED_ALLOWED_PATHS):
                logger.info('Blocking disabled tenant %s from path %s', tenant.id, request.path)
                return redirect('account_disabled')
            return self.get_response(request)

        tenant.update_subscription_state()

        if tenant.subscription_status == 'cancelled':
            if not any(request.path.startswith(path) for path in self.BILLING_PATHS):
                logger.info('Redirecting cancelled tenant %s from path %s', tenant.id, request.path)
                return redirect('account_cancelled')
            return self.get_response(request)

        if tenant.subscription_status == 'paused':
            if not any(request.path.startswith(path) for path in self.BILLING_PATHS):
                logger.info('Redirecting paused tenant %s to paused page from %s', tenant.id, request.path)
                messages.warning(request, 'Your account is paused. Reactivate your subscription to restore full access.')
                return redirect('account_paused')
            return self.get_response(request)

        if tenant.subscription_status == 'suspended':
            if not any(request.path.startswith(path) for path in self.BILLING_PATHS):
                logger.info('Blocking suspended tenant %s from path %s', tenant.id, request.path)
                return redirect('account_suspended')
            return self.get_response(request)

        if tenant.is_read_only() and request.method not in self.SAFE_READ_ONLY_METHODS:
            if not any(request.path.startswith(path) for path in self.BILLING_PATHS):
                logger.info('Blocking write request for read-only tenant %s on %s', tenant.id, request.path)
                messages.warning(request, 'Your account is in read-only mode. Please renew your subscription to make changes.')
                return redirect('billing_dashboard')

        return self.get_response(request)
