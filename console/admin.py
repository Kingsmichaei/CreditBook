from django.contrib import admin

from .models import AdminAction


@admin.register(AdminAction)
class AdminActionAdmin(admin.ModelAdmin):
    """Read-only view of the owner console audit trail."""

    list_display = ('tenant_name', 'action', 'previous_status', 'new_status', 'actor', 'created_at')
    list_filter = ('action', 'created_at')
    search_fields = ('tenant_name', 'note', 'actor__username')

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
