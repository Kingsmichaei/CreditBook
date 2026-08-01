from django.contrib import admin
from .models import Customer, Sale, Debt, Expense, Income, Staff

@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ['name', 'phone', 'email', 'created_at']
    search_fields = ['name', 'phone']

@admin.register(Sale)
class SaleAdmin(admin.ModelAdmin):
    list_display = ['product', 'customer', 'total', 'payment_method', 'date']
    list_filter = ['payment_method', 'date']
    search_fields = ['product', 'customer__name']

@admin.register(Debt)
class DebtAdmin(admin.ModelAdmin):
    list_display = ['customer', 'amount', 'is_paid', 'due_date', 'created_at']
    list_filter = ['is_paid']

@admin.register(Expense)
class ExpenseAdmin(admin.ModelAdmin):
    list_display = ['description', 'category', 'amount', 'date']
    list_filter = ['category']

@admin.register(Income)
class IncomeAdmin(admin.ModelAdmin):
    list_display = ['description', 'category', 'amount', 'date']

@admin.register(Staff)
class StaffAdmin(admin.ModelAdmin):
    list_display = ['name', 'role', 'phone', 'is_active', 'date_joined']
    list_filter = ['role', 'is_active']
