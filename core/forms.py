from django import forms
from django.contrib.auth import get_user_model, authenticate
from django.contrib.auth.forms import AuthenticationForm
from django.db.models import Q
from .models import Customer, Sale, Debt, Expense, Income, Staff


def normalize_phone(value):
    if not value:
        return ''
    digits = ''.join(ch for ch in value if ch.isdigit())
    if digits.startswith('234') and len(digits) == 13:
        return '0' + digits[3:]
    if digits.startswith('0') and len(digits) == 11:
        return digits
    return digits


class RegistrationForm(forms.Form):
    business_name = forms.CharField(max_length=200, widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Your business name'}))
    owner_name = forms.CharField(max_length=200, widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Owner or founder name'}))
    email = forms.EmailField(widget=forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'name@company.com'}))
    phone = forms.CharField(max_length=20, widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': '08012345678'}))
    password1 = forms.CharField(widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': 'Create a password'}))
    password2 = forms.CharField(widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': 'Repeat password'}))

    def clean_email(self):
        email = self.cleaned_data['email']
        if get_user_model().objects.filter(email__iexact=email).exists():
            raise forms.ValidationError('That email is already registered.')
        return email

    def clean(self):
        cleaned = super().clean()
        password1 = cleaned.get('password1')
        password2 = cleaned.get('password2')
        if password1 and password2 and password1 != password2:
            raise forms.ValidationError('The two password fields did not match.')
        return cleaned


class EmailOrPhoneAuthenticationForm(AuthenticationForm):
    username = forms.CharField(
        label='Email address or phone number',
        max_length=254,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Email address or phone number'})
    )

    def clean(self):
        username = self.cleaned_data.get('username')
        password = self.cleaned_data.get('password')

        if username and password:
            user_model = get_user_model()

            if '@' in username:
                user = user_model.objects.filter(Q(email__iexact=username) | Q(username__iexact=username)).first()
            else:
                normalized_phone = normalize_phone(username)
                candidates = user_model.objects.filter(username__iexact=username)
                if normalized_phone:
                    candidates = candidates | user_model.objects.filter(last_name__iexact=normalized_phone)
                user = candidates.first()

            if user is not None and user.check_password(password):
                self.user_cache = user
                self.confirm_login_allowed(user)
                return self.cleaned_data

        self.user_cache = None
        raise forms.ValidationError('Incorrect email, phone number, or password. Please try again.')


class ProfileForm(forms.Form):
    business_name = forms.CharField(max_length=200, widget=forms.TextInput(attrs={'class': 'form-control'}))
    currency = forms.CharField(max_length=10, required=False, widget=forms.TextInput(attrs={'class': 'form-control'}))
    email = forms.EmailField(widget=forms.EmailInput(attrs={'class': 'form-control'}))
    phone = forms.CharField(max_length=20, required=False, widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': '08012345678'}))

    def __init__(self, *args, user=None, tenant=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        self.tenant = tenant
        if user is not None:
            self.fields['email'].initial = user.email
            self.fields['phone'].initial = user.last_name
        if tenant is not None:
            self.fields['business_name'].initial = tenant.business_name
            self.fields['currency'].initial = tenant.currency

    def clean_phone(self):
        phone = self.cleaned_data.get('phone') or ''
        phone = normalize_phone(phone)
        if self.user is not None and self.user.last_name == phone:
            return phone
        if phone and get_user_model().objects.filter(last_name__iexact=phone).exists():
            raise forms.ValidationError('That phone number is already registered.')
        return phone

    def clean_email(self):
        email = self.cleaned_data['email']
        if self.user is not None and self.user.email.lower() == email.lower():
            return email
        if get_user_model().objects.filter(email__iexact=email).exists():
            raise forms.ValidationError('That email is already registered.')
        return email


class CustomerForm(forms.ModelForm):
    class Meta:
        model = Customer
        fields = ['name', 'phone', 'email', 'address', 'notes']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Full name'}),
            'phone': forms.TextInput(attrs={'class': 'form-control', 'placeholder': '08012345678'}),
            'email': forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'email@example.com'}),
            'address': forms.Textarea(attrs={'class': 'form-control', 'rows': 2, 'placeholder': 'Address'}),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 2, 'placeholder': 'Additional notes'}),
        }


class SaleForm(forms.ModelForm):
    class Meta:
        model = Sale
        fields = ['customer', 'product', 'description', 'quantity', 'unit_price', 'payment_method', 'date', 'notes']
        widgets = {
            'customer': forms.Select(attrs={'class': 'form-select'}),
            'product': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Product / Service name'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
            'quantity': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'min': '0.01'}),
            'unit_price': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'min': '0'}),
            'payment_method': forms.Select(attrs={'class': 'form-select'}),
            'date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
        }


class DebtForm(forms.ModelForm):
    class Meta:
        model = Debt
        fields = ['customer', 'amount', 'description', 'due_date']
        widgets = {
            'customer': forms.Select(attrs={'class': 'form-select'}),
            'amount': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'min': '0'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'What goods/services were taken on credit?'}),
            'due_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
        }


class ExpenseForm(forms.ModelForm):
    class Meta:
        model = Expense
        fields = ['category', 'description', 'amount', 'date', 'receipt_note']
        widgets = {
            'category': forms.Select(attrs={'class': 'form-select'}),
            'description': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Brief description'}),
            'amount': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'min': '0'}),
            'date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'receipt_note': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
        }


class IncomeForm(forms.ModelForm):
    class Meta:
        model = Income
        fields = ['description', 'category', 'amount', 'date', 'notes']
        widgets = {
            'description': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Income description'}),
            'category': forms.Select(attrs={'class': 'form-select'}),
            'amount': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'min': '0'}),
            'date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
        }


class StaffForm(forms.ModelForm):
    email = forms.EmailField(required=True, widget=forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'email@example.com'}))
    phone = forms.CharField(required=True, widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': '08012345678'}))
    password = forms.CharField(required=False, widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': 'Leave blank to keep existing password'}))
    confirm_password = forms.CharField(required=False, widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': 'Confirm password'}))

    class Meta:
        model = Staff
        fields = ['name', 'role', 'phone', 'email', 'address', 'salary', 'is_active', 'date_joined']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Full name'}),
            'role': forms.Select(attrs={'class': 'form-select'}),
            'address': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
            'salary': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'min': '0'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'date_joined': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.user:
            self.fields['email'].initial = self.instance.user.email or self.instance.email
            self.fields['phone'].initial = self.instance.user.last_name or self.instance.phone

    def clean(self):
        cleaned_data = super().clean()
        password = cleaned_data.get('password') or ''
        confirm_password = cleaned_data.get('confirm_password') or ''
        if password or confirm_password:
            if password != confirm_password:
                raise forms.ValidationError('Passwords do not match.')
        return cleaned_data

    def clean_email(self):
        email = self.cleaned_data.get('email') or ''
        if self.instance and self.instance.user and self.instance.user.email.lower() == email.lower():
            return email
        if get_user_model().objects.filter(email__iexact=email).exists():
            raise forms.ValidationError('That email is already registered.')
        return email

    def clean_phone(self):
        phone = self.cleaned_data.get('phone') or ''
        return normalize_phone(phone)
