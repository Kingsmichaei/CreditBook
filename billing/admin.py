from django.contrib import admin

from .models import BillingLog


@admin.register(BillingLog)
class BillingLogAdmin(admin.ModelAdmin):
    """Admin configuration for billing logs."""

    list_display = ('tenant', 'order_reference', 'status', 'amount', 'created_at')
    list_filter = ('status', 'created_at')
    search_fields = ('tenant__business_name', 'order_reference', 'nomba_txn_id')
    readonly_fields = ('raw_response',)
