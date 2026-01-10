from django import forms
from django.contrib.auth.forms import UserCreationForm, UserChangeForm
from .models import CustomUser


class CustomUserCreationForm(UserCreationForm):
    # We use 'password1' and 'password2' (NO UNDERSCORES) to match Django's defaults.
    password1 = forms.CharField(
        label='Password',
        widget=forms.PasswordInput(),
        help_text="Password must be at least 8 characters long."
    )
    password2 = forms.CharField(
        label='Password confirmation',
        widget=forms.PasswordInput(),
        help_text="Enter the same password as before, for verification."
    )

    class Meta:
        model = CustomUser
        fields = ('email', 'username')

    def clean(self):
        cleaned_data = super().clean()  #Checks the Rules. "Is the email unique? Is the text too long? Is the field required?"
        p1 = cleaned_data.get("password1")
        p2 = cleaned_data.get("password2")

        # Manually check matching (Django does this too, but we double-check)
        if p1 and p2 and p1 != p2:
            self.add_error("password2", "Passwords do not match")

        return cleaned_data

    def save(self, commit=True):
        user = super().save(commit=False)        #Doing the Mapping. "Copying data from the form inputs into the Model Object fields."
        user.set_password(self.cleaned_data["password1"])
        if commit:
            user.save()
        return user


class CustomUserChangeForm(UserChangeForm):
    class Meta:
        model = CustomUser
        fields = ('email', 'username')