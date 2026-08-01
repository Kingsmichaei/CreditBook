"""
Management command to seed demo data for SYLVALINE Ventures.
Run: python manage.py seed_demo
"""
from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import date, timedelta
import random

from core.models import Customer, Sale, Debt, Expense, Income, Staff


class Command(BaseCommand):
    help = 'Seeds the database with demo data for Complete SYLVALINE Ventures'

    def handle(self, *args, **kwargs):
        self.stdout.write('\n🌱 Seeding demo data...\n')

        # Staff
        staff_data = [
            {'name': 'Chukwuemeka Okafor', 'role': 'owner',      'phone': '08012345678', 'salary': 0},
            {'name': 'Adaeze Nwosu',        'role': 'manager',    'phone': '08023456789', 'salary': 120000},
            {'name': 'Tunde Adeyemi',       'role': 'cashier',    'phone': '08034567890', 'salary': 80000},
            {'name': 'Ngozi Eze',           'role': 'salesperson','phone': '08045678901', 'salary': 75000},
            {'name': 'Emeka Obiora',        'role': 'accountant', 'phone': '08056789012', 'salary': 95000},
        ]
        for s in staff_data:
            Staff.objects.get_or_create(name=s['name'], defaults={
                'role': s['role'], 'phone': s['phone'],
                'salary': s['salary'], 'is_active': True,
                'date_joined': date.today() - timedelta(days=random.randint(30,365))
            })
        self.stdout.write('  ✅ Staff created')

        # Customers
        customers_data = [
            {'name': 'Alhaji Musa Danjuma',    'phone': '08067890123'},
            {'name': 'Mrs Chioma Obi',          'phone': '08078901234'},
            {'name': 'Mr Babatunde Fashola',    'phone': '08089012345'},
            {'name': 'Fatima Al-Hassan',         'phone': '08090123456'},
            {'name': 'Chief Emeka Eze',          'phone': '08001234567'},
            {'name': 'Aisha Mohammed',           'phone': '07012345678'},
            {'name': 'Johnson Adebayo',          'phone': '07023456789'},
            {'name': 'Grace Nkechi Okonkwo',     'phone': '07034567890'},
        ]
        customers = []
        for c in customers_data:
            obj, _ = Customer.objects.get_or_create(name=c['name'], defaults={'phone': c['phone']})
            customers.append(obj)
        self.stdout.write('  ✅ Customers created')

        # Sales
        products = [
            ('Rice (50kg bag)', 35000, 'stock'),
            ('Cooking Oil (25L)',22000, 'stock'),
            ('Sugar (50kg)',    28000, 'stock'),
            ('Wholesale Flour', 18000, 'stock'),
            ('Beverages Crate', 12500, 'stock'),
            ('Tomatoes (basket)',8000, 'stock'),
            ('Palm Oil (25L)',  19500, 'stock'),
            ('Garri (100kg)',   15000, 'stock'),
        ]
        payment_methods = ['cash', 'cash', 'cash', 'transfer', 'pos', 'credit']
        today = date.today()
        for i in range(30):
            d = today - timedelta(days=random.randint(0, 60))
            product, price, _ = random.choice(products)
            qty = random.randint(1, 5)
            customer = random.choice(customers + [None, None])
            pm = random.choice(payment_methods)
            sale = Sale.objects.create(
                customer=customer, product=product,
                quantity=qty, unit_price=price,
                payment_method=pm, date=d,
            )
            if pm == 'credit' and customer:
                Debt.objects.create(
                    customer=customer, amount=sale.total,
                    description=f'Credit purchase: {product}',
                    due_date=d + timedelta(days=30),
                )
        self.stdout.write('  ✅ Sales recorded')

        # Expenses
        expense_items = [
            ('Monthly shop rent',         'rent',        150000),
            ('PHCN electricity bill',     'utilities',    22000),
            ('Staff salaries - October',  'salary',      370000),
            ('Stock restocking — rice',   'stock',       420000),
            ('Transport — delivery truck','transport',    35000),
            ('Advert — Facebook/IG',      'marketing',    25000),
            ('Generator maintenance',     'maintenance',  18000),
            ('New shelving units',        'equipment',    85000),
            ('NAFDAC/SON registration',   'tax',          12000),
            ('Stationery & office supply','other',         8500),
        ]
        for desc, cat, amt in expense_items:
            Expense.objects.create(
                description=desc, category=cat, amount=amt,
                date=today - timedelta(days=random.randint(0, 30))
            )
        self.stdout.write('  ✅ Expenses recorded')

        # Income
        income_items = [
            ('October wholesale revenue', 'sales',      1850000),
            ('Retail counter sales Oct',  'sales',       620000),
            ('Investor top-up capital',   'investment',  500000),
            ('Refund — returned goods',   'refund',       35000),
        ]
        for desc, cat, amt in income_items:
            Income.objects.create(
                description=desc, category=cat, amount=amt,
                date=today - timedelta(days=random.randint(0, 30))
            )
        self.stdout.write('  ✅ Income recorded')

        self.stdout.write('\n✅ Demo data seeded successfully!\n')
        self.stdout.write('   Login at http://127.0.0.1:8000\n\n')
