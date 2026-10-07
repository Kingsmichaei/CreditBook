from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from billing.models import BillingLog
from core.models import Customer, Tenant, TenantMembership

from .models import AdminAction


@override_settings(SUBSCRIPTION_PRICE_NGN='5000')
class ConsoleTestCase(TestCase):
    def setUp(self):
        User = get_user_model()
        self.owner = User.objects.create_superuser(username='platform', email='platform@creditbook.com', password='pw')
        self.merchant = User.objects.create_user(username='merchant', email='m@shop.com', password='pw')
        self.tenant = Tenant.objects.create(
            owner=self.merchant, business_name='Mama Put Foods',
            trial_ends_at=timezone.now().date() + timedelta(days=10),
            nomba_token_key='tok_123', nomba_card_pan='539983******1234',
        )
        TenantMembership.objects.create(user=self.merchant, tenant=self.tenant, role='owner')
        Customer.objects.create(tenant=self.tenant, name='Ada')
        BillingLog.objects.create(tenant=self.tenant, order_reference='ref-1', amount=Decimal('5000'), status='success')

    def action(self, name, data):
        return self.client.post(reverse('console:business_action', args=[self.tenant.pk, name]), data)


class AccessTests(ConsoleTestCase):
    def test_anonymous_user_is_sent_to_login(self):
        response = self.client.get(reverse('console:overview'))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('login'), response['Location'])

    def test_tenant_owner_cannot_see_console(self):
        self.client.force_login(self.merchant)
        for name in ('overview', 'businesses', 'payments', 'activity'):
            self.assertEqual(self.client.get(reverse(f'console:{name}')).status_code, 404)
        self.assertEqual(self.client.get(reverse('console:business_detail', args=[self.tenant.pk])).status_code, 404)
        self.assertEqual(self.action('disable', {'reason': 'x'}).status_code, 404)
        self.tenant.refresh_from_db()
        self.assertFalse(self.tenant.is_disabled)

    def test_superuser_without_business_lands_on_console_after_login(self):
        response = self.client.post(reverse('login'), {'username': 'platform', 'password': 'pw'})
        self.assertRedirects(response, reverse('console:overview'))


class PageTests(ConsoleTestCase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.owner)

    def test_overview_shows_platform_metrics(self):
        Tenant.objects.filter(pk=self.tenant.pk).update(subscription_status='active')
        response = self.client.get(reverse('console:overview'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['active_count'], 1)
        self.assertEqual(response.context['mrr'], Decimal('5000'))
        self.assertEqual(response.context['revenue_all_time'], Decimal('5000'))
        self.assertEqual(sum(response.context['chart_revenue']), 5000.0)

    def test_business_list_search_filter_and_export(self):
        other = Tenant.objects.create(owner=self.owner, business_name='Other Shop', subscription_status='cancelled')
        response = self.client.get(reverse('console:businesses'), {'q': 'mama'})
        self.assertEqual([t.pk for t in response.context['page']], [self.tenant.pk])
        self.assertEqual(response.context['page'][0].revenue, Decimal('5000'))

        response = self.client.get(reverse('console:businesses'), {'status': 'cancelled'})
        self.assertEqual([t.pk for t in response.context['page']], [other.pk])

        response = self.client.get(reverse('console:businesses'), {'export': 'csv'})
        self.assertEqual(response['Content-Type'], 'text/csv')
        self.assertIn('Mama Put Foods', response.content.decode())

    def test_detail_sees_other_tenants_data_even_when_owner_has_own_business(self):
        own = Tenant.objects.create(owner=self.owner, business_name='Platform HQ')
        TenantMembership.objects.create(user=self.owner, tenant=own, role='owner')
        response = self.client.get(reverse('console:business_detail', args=[self.tenant.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['usage']['customers'], 1)

    def test_action_modals_render_outside_main_content(self):
        # Inside .main-content (z-index: 1) the modals sit beneath Bootstrap's backdrop and the page freezes.
        html = self.client.get(reverse('console:business_detail', args=[self.tenant.pk])).content.decode()
        self.assertGreater(html.index('id="activateModal"'), html.index('</main>'))

    def test_payments_and_activity_pages_render(self):
        self.assertContains(self.client.get(reverse('console:payments')), 'Mama Put Foods')
        self.assertEqual(self.client.get(reverse('console:activity')).status_code, 200)


class ActionTests(ConsoleTestCase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.owner)

    def test_mark_as_subscribed_records_manual_payment(self):
        Tenant.objects.filter(pk=self.tenant.pk).update(subscription_status='paused', failed_payment_count=2)
        response = self.action('activate', {'days': 30, 'amount': '5000', 'reference': 'TRF-99', 'note': 'Paid by transfer'})
        self.assertRedirects(response, reverse('console:business_detail', args=[self.tenant.pk]))

        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.subscription_status, 'active')
        self.assertEqual(self.tenant.failed_payment_count, 0)
        self.assertEqual(self.tenant.next_billing_date, timezone.now().date() + timedelta(days=30))
        manual = BillingLog.objects.get(tenant=self.tenant, payment_method='manual')
        self.assertEqual((manual.status, manual.amount, manual.nomba_txn_id), ('success', Decimal('5000'), 'TRF-99'))
        log = AdminAction.objects.get(action='activate')
        self.assertEqual((log.previous_status, log.new_status, log.actor), ('paused', 'active', self.owner))

    def test_complimentary_subscription_records_no_payment(self):
        self.action('activate', {'days': 14, 'amount': ''})
        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.subscription_status, 'active')
        self.assertFalse(BillingLog.objects.filter(payment_method='manual').exists())

    def test_terminate_requires_confirmation(self):
        response = self.action('terminate', {'reason': 'Fraud', 'remove_card': 'on', 'confirm': 'nope'})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.context['open_modal'], 'terminate_form')
        self.tenant.refresh_from_db()
        self.assertNotEqual(self.tenant.subscription_status, 'cancelled')

    def test_terminate_stops_billing_and_removes_card(self):
        Tenant.objects.filter(pk=self.tenant.pk).update(subscription_status='active', next_billing_date=timezone.now().date())
        self.action('terminate', {'reason': 'Requested by customer', 'remove_card': 'on', 'confirm': 'TERMINATE'})
        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.subscription_status, 'cancelled')
        self.assertIsNone(self.tenant.next_billing_date)
        self.assertEqual(self.tenant.nomba_token_key, '')

    def test_extend_trial(self):
        Tenant.objects.filter(pk=self.tenant.pk).update(subscription_status='read_only', trial_ends_at=timezone.now().date() - timedelta(days=2))
        self.action('extend_trial', {'days': 7})
        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.subscription_status, 'trial')
        self.assertEqual(self.tenant.trial_ends_at, timezone.now().date() + timedelta(days=7))

    def test_unknown_action_is_404(self):
        self.assertEqual(self.action('delete', {}).status_code, 404)


class EnforcementTests(ConsoleTestCase):
    def test_disabled_business_is_locked_out_until_enabled(self):
        self.client.force_login(self.owner)
        self.action('disable', {'reason': 'Chargeback abuse'})
        self.tenant.refresh_from_db()
        self.assertTrue(self.tenant.is_disabled)

        self.client.force_login(self.merchant)
        self.assertRedirects(self.client.get(reverse('dashboard')), reverse('account_disabled'))
        self.assertRedirects(self.client.get(reverse('billing_subscribe')), reverse('account_disabled'))
        self.assertContains(self.client.get(reverse('account_disabled')), 'has been disabled')

        self.client.force_login(self.owner)
        self.action('enable', {'note': 'Resolved'})
        self.client.force_login(self.merchant)
        self.assertEqual(self.client.get(reverse('dashboard')).status_code, 200)
        self.assertEqual(AdminAction.objects.filter(tenant=self.tenant).count(), 2)

    def test_terminated_business_must_resubscribe(self):
        self.client.force_login(self.owner)
        self.action('terminate', {'reason': 'Ended', 'confirm': 'TERMINATE'})

        self.client.force_login(self.merchant)
        self.assertRedirects(self.client.get(reverse('dashboard')), reverse('account_cancelled'))
        self.assertEqual(self.client.get(reverse('billing_subscribe')).status_code, 200)
