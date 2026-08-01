from django.shortcuts import redirect
from django.urls import resolve
from .models import Tenant, TenantMembership, get_current_tenant, set_current_tenant, clear_current_tenant


class TenantMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        clear_current_tenant()
        request.tenant = None

        if request.user.is_authenticated:
            membership = TenantMembership.objects.filter(user=request.user).order_by('created_at').first()
            if membership:
                request.tenant = membership.tenant
                set_current_tenant(membership.tenant)

        response = self.get_response(request)
        clear_current_tenant()
        return response
