"""Audit trail for actions the platform owner takes against tenants."""
from django.conf import settings
from django.db import models

from core.models import Tenant


class AdminAction(models.Model):
    ACTIONS = [
        ('activate', 'Marked as subscribed'),
        ('terminate', 'Terminated subscription'),
        ('extend_trial', 'Extended trial'),
        ('disable', 'Disabled business'),
        ('enable', 'Enabled business'),
    ]

    # SET_NULL keeps the audit trail when a tenant deletes their account; tenant_name preserves who it was.
    tenant = models.ForeignKey(Tenant, on_delete=models.SET_NULL, null=True, blank=True, related_name='admin_actions')
    tenant_name = models.CharField(max_length=200)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='console_actions')
    action = models.CharField(max_length=30, choices=ACTIONS)
    previous_status = models.CharField(max_length=20, blank=True)
    new_status = models.CharField(max_length=20, blank=True)
    note = models.TextField(blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.get_action_display()} — {self.tenant_name}'
