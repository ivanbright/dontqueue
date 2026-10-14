"""Forms for registering customers into a queue."""

from django import forms

from core.forms import style_fields


class RegisterForm(forms.Form):
    """Used by receptionists to add a walk-in customer."""

    full_name = forms.CharField(max_length=150)
    phone = forms.CharField(max_length=32, required=False)
    email = forms.EmailField(required=False)
    priority = forms.IntegerField(required=False, initial=0)
    note = forms.CharField(max_length=280, required=False, widget=forms.Textarea(attrs={"rows": 2}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        style_fields(self)


class PublicJoinForm(forms.Form):
    """Used by customers on the public page."""

    full_name = forms.CharField(max_length=150, label="Your name")
    phone = forms.CharField(max_length=32, required=False, label="Mobile (optional)")
    email = forms.EmailField(required=False, label="Email (optional)")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        style_fields(self)
