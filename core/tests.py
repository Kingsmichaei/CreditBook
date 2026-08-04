from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase
from django.urls import reverse

from .models import Customer, Sale, Staff, Tenant, TenantMembership


class ExportViewsTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username='tester', password='secret123')
        self.customer = Customer.objects.create(name='Ada', phone='08012345678')
        self.sale = Sale.objects.create(
            customer=self.customer,
            product='Rice bag',
            description='Wholesale sale',
            quantity=2,
            unit_price=2500,
            payment_method='cash',
            date='2026-07-25',
        )

    def test_sales_export_returns_csv(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse('sales_export'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'text/csv')
        self.assertIn('product', response.content.decode('utf-8').lower())
        self.assertIn('rice bag', response.content.decode('utf-8').lower())


class TenantRegistrationTests(TestCase):
    def test_authenticated_user_without_tenant_can_access_registration(self):
        user = get_user_model().objects.create_user(username='onboarder', password='StrongPass123')
        self.client.force_login(user)

        response = self.client.get(reverse('register'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Let's Get Started")

    def test_registration_creates_tenant_and_logs_user_in(self):
        response = self.client.post(reverse('register'), {
            'business_name': 'CreditBook Demo',
            'owner_name': 'Balance Owner',
            'email': 'owner@creditbook.com',
            'phone': '08012345678',
            'password1': 'StrongPass123',
            'password2': 'StrongPass123',
        })

        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, reverse('dashboard'))

        user = get_user_model().objects.get(username='owner@creditbook.com')
        tenant = Tenant.objects.get(owner=user)
        self.assertEqual(tenant.business_name, 'CreditBook Demo')
        self.assertTrue(TenantMembership.objects.filter(user=user, tenant=tenant, role='owner').exists())

    def test_tenant_scopes_records_to_the_current_business(self):
        user = get_user_model().objects.create_user(username='tenantuser', password='StrongPass123')
        tenant_a = Tenant.objects.create(owner=user, business_name='Northwind', slug='northwind')
        TenantMembership.objects.create(user=user, tenant=tenant_a, role='owner')

        tenant_b = Tenant.objects.create(owner=user, business_name='Acme', slug='acme')
        TenantMembership.objects.create(user=user, tenant=tenant_b, role='owner')

        Customer.objects.create(tenant=tenant_a, name='Ada')
        Customer.objects.create(tenant=tenant_b, name='Grace')

        self.client.force_login(user)
        response = self.client.get(reverse('customers_list'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Ada')
        self.assertNotContains(response, 'Grace')


class LoginAuthenticationTests(TestCase):
    def test_login_accepts_email_as_username(self):
        user = get_user_model().objects.create_user(username='owner@creditbook.com', email='owner@creditbook.com', password='StrongPass123')
        tenant = Tenant.objects.create(owner=user, business_name='CreditBook', slug='creditbook')
        TenantMembership.objects.create(user=user, tenant=tenant, role='owner')

        response = self.client.post(reverse('login'), {'username': 'owner@creditbook.com', 'password': 'StrongPass123'})

        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, reverse('dashboard'))

    def test_login_accepts_phone_as_username(self):
        user = get_user_model().objects.create_user(username='08012345678', email='phone@example.com', password='StrongPass123', last_name='08012345678')
        tenant = Tenant.objects.create(owner=user, business_name='CreditBook', slug='creditbook-phone')
        TenantMembership.objects.create(user=user, tenant=tenant, role='owner')

        response = self.client.post(reverse('login'), {'username': '08012345678', 'password': 'StrongPass123'})

        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, reverse('dashboard'))

    def test_login_redirects_to_onboarding_for_users_without_a_workspace(self):
        user = get_user_model().objects.create_user(username='newuser', email='newuser@example.com', password='StrongPass123')
        response = self.client.post(reverse('login'), {'username': 'newuser', 'password': 'StrongPass123'})

        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, reverse('register'))


class AccountManagementTests(TestCase):
    def test_profile_page_is_available_from_the_app(self):
        user = get_user_model().objects.create_user(username='profileuser', email='profile@example.com', password='StrongPass123')
        tenant = Tenant.objects.create(owner=user, business_name='Profile Co', slug='profileco')
        TenantMembership.objects.create(user=user, tenant=tenant, role='owner')

        self.client.force_login(user)
        response = self.client.get(reverse('profile_view'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Business profile')

    def test_delete_account_sends_verification_email_and_deletes_after_confirmation(self):
        user = get_user_model().objects.create_user(username='deleteuser', email='delete@example.com', password='StrongPass123')
        tenant = Tenant.objects.create(owner=user, business_name='Delete Co', slug='deleteco')
        TenantMembership.objects.create(user=user, tenant=tenant, role='owner')

        self.client.force_login(user)
        response = self.client.post(reverse('delete_account'), {'confirm_email': user.email})

        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, reverse('delete_account'))
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('Confirm your CreditBook account deletion', mail.outbox[0].subject)

        confirmation_link = mail.outbox[0].body.split('http://testserver')[1].split('\n', 1)[0]
        confirmation_response = self.client.get(confirmation_link)

        self.assertEqual(confirmation_response.status_code, 302)
        self.assertRedirects(confirmation_response, reverse('landing'))
        self.assertFalse(get_user_model().objects.filter(pk=user.pk).exists())


class StaffNavigationTests(TestCase):
    def test_staff_link_is_visible_for_owner_without_superuser(self):
        user = get_user_model().objects.create_user(username='owneruser', email='owner@example.com', password='StrongPass123')
        tenant = Tenant.objects.create(owner=user, business_name='Staff Co', slug='staffco')
        TenantMembership.objects.create(user=user, tenant=tenant, role='owner')

        self.client.force_login(user)
        response = self.client.get(reverse('dashboard'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Staff')

    def test_staff_link_is_hidden_for_staff_member(self):
        owner = get_user_model().objects.create_user(username='owneruser2', email='owner2@example.com', password='StrongPass123')
        tenant = Tenant.objects.create(owner=owner, business_name='Staff Co', slug='staffco2')
        TenantMembership.objects.create(user=owner, tenant=tenant, role='owner')

        staff_user = get_user_model().objects.create_user(username='staffuser', email='staff@example.com', password='StrongPass123')
        TenantMembership.objects.create(user=staff_user, tenant=tenant, role='staff')

        self.client.force_login(staff_user)
        response = self.client.get(reverse('dashboard'))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'Staff')
        self.assertNotContains(response, 'Billing')
        self.assertNotContains(response, 'Profile')

    def test_billing_button_is_hidden_for_staff_member_on_dashboard(self):
        owner = get_user_model().objects.create_user(username='owneruser3', email='owner3@example.com', password='StrongPass123')
        tenant = Tenant.objects.create(owner=owner, business_name='Billing Co', slug='billingco')
        TenantMembership.objects.create(user=owner, tenant=tenant, role='owner')

        staff_user = get_user_model().objects.create_user(username='staffuser2', email='staff2@example.com', password='StrongPass123')
        TenantMembership.objects.create(user=staff_user, tenant=tenant, role='staff')

        self.client.force_login(staff_user)
        response = self.client.get(reverse('dashboard'))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'Billing')


class StaffAuthenticationTests(TestCase):
    def test_staff_can_create_login_account(self):
        self.admin = get_user_model().objects.create_user(username='admin', password='secret123')
        self.client.force_login(self.admin)

        response = self.client.post(reverse('staff_add'), {
            'name': 'Jane Staff',
            'role': 'cashier',
            'phone': '08012345678',
            'email': 'jane@example.com',
            'address': 'Lagos',
            'salary': '15000',
            'is_active': 'on',
            'date_joined': '2026-07-26',
            'password': 'staffpass123',
            'confirm_password': 'staffpass123',
        })

        self.assertEqual(response.status_code, 302)
        self.assertTrue(get_user_model().objects.filter(username='jane@example.com').exists())
        self.assertTrue(self.client.login(username='jane@example.com', password='staffpass123'))
        self.assertTrue(Staff.objects.filter(name='Jane Staff', user__username='jane@example.com').exists())
