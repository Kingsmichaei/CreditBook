from datetime import timedelta
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from core.models import Tenant


class SyncBillingStatusCommandTests(TestCase):
    def setUp(self):
        self.owner = get_user_model().objects.create_user(username='owner', password='pw')
        self.today = timezone.now().date()

    def test_moves_expired_trial_to_read_only(self):
        tenant = Tenant.objects.create(owner=self.owner, business_name='Expired', trial_ends_at=self.today - timedelta(days=2))
        out = StringIO()
        call_command('sync_billing_status', stdout=out)
        tenant.refresh_from_db()
        self.assertEqual(tenant.subscription_status, 'read_only')
        self.assertIn('from trial to read_only', out.getvalue())

    def test_normalizes_stale_billing_date_for_card_holders(self):
        tenant = Tenant.objects.create(
            owner=self.owner, business_name='Stale', subscription_status='active',
            next_billing_date=self.today - timedelta(days=5), nomba_token_key='tok',
        )
        call_command('sync_billing_status', stdout=StringIO())
        tenant.refresh_from_db()
        self.assertEqual(tenant.next_billing_date, self.today)
