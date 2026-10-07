from django import forms


class ActivateSubscriptionForm(forms.Form):
    days = forms.IntegerField(min_value=1, max_value=730, initial=30, label='Subscription length (days)')
    amount = forms.DecimalField(
        required=False, min_value=0, max_digits=12, decimal_places=2, label='Amount received (₦)',
        help_text='Leave blank for a complimentary subscription. If set, a successful payment is recorded.',
    )
    reference = forms.CharField(required=False, max_length=200, label='Payment reference',
                                help_text='Bank transfer reference, receipt number, etc.')
    note = forms.CharField(required=False, widget=forms.Textarea(attrs={'rows': 2}), label='Internal note')


class TerminateSubscriptionForm(forms.Form):
    reason = forms.CharField(widget=forms.Textarea(attrs={'rows': 2}), label='Reason')
    remove_card = forms.BooleanField(required=False, initial=True, label='Remove saved card')
    confirm = forms.CharField(label='Type TERMINATE to confirm')

    def clean_confirm(self):
        if self.cleaned_data['confirm'].strip().upper() != 'TERMINATE':
            raise forms.ValidationError('Type TERMINATE to confirm.')
        return self.cleaned_data['confirm']


class ExtendTrialForm(forms.Form):
    days = forms.IntegerField(min_value=1, max_value=365, initial=7, label='Extra days')
    note = forms.CharField(required=False, widget=forms.Textarea(attrs={'rows': 2}), label='Internal note')


class DisableBusinessForm(forms.Form):
    reason = forms.CharField(widget=forms.Textarea(attrs={'rows': 2}), label='Reason')


class EnableBusinessForm(forms.Form):
    note = forms.CharField(required=False, widget=forms.Textarea(attrs={'rows': 2}), label='Internal note')
