from django.core.management.base import BaseCommand
from django.utils import timezone

from core.models import Tenant


class Command(BaseCommand):
    """Reconcile billing-related tenant state when it appears inconsistent."""

    help = 'Synchronize tenant subscription status with billing dates.'

    def handle(self, *args, **options):
        today = timezone.now().date()
        for tenant in Tenant.objects.all():
            previous_status = tenant.subscription_status
            tenant.update_subscription_state()
            if tenant.subscription_status != previous_status:
                self.stdout.write(self.style.WARNING(
                    f'Updated tenant {tenant.business_name} from {previous_status} to {tenant.subscription_status}'
                ))
            elif tenant.subscription_status in ['active', 'past_due'] and tenant.next_billing_date and tenant.next_billing_date < today and tenant.nomba_token_key:
                tenant.next_billing_date = today
                tenant.save(update_fields=['next_billing_date'])
                self.stdout.write(self.style.SUCCESS(f'Normalized next billing date for {tenant.business_name}'))
