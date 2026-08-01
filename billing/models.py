"""Billing models for subscription lifecycle management."""
from decimal import Decimal
import json

from django.conf import settings
from django.db import models
from django.utils import timezone

from core.models import Tenant


class BillingLog(models.Model):
    """Tracks payment attempts and their outcomes for a tenant."""

    STATUS = [('pending', 'Pending'), ('success', 'Success'), ('failed', 'Failed'), ('refunded', 'Refunded')]
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='billing_logs')
    order_reference = models.CharField(max_length=100, unique=True)
    amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    status = models.CharField(max_length=20, choices=STATUS, default='pending')
    is_tokenized = models.BooleanField(default=False)
    nomba_txn_id = models.CharField(max_length=200, blank=True)
    payment_method = models.CharField(max_length=50, blank=True)
    failure_reason = models.TextField(blank=True)
    raw_response = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.tenant.business_name} - {self.order_reference}'
