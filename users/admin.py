from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import CustomUser
from .forms import CustomUserCreationForm, CustomUserChangeForm

"""
1. we create a DB and modified it using the AbstractUser

2.we only changed the DB looks,but not how they are created ,so now we modift the BaseUserManager within which we hard-code the login fields and the superuser fields

3.now we modify the admin page fields using the UserAdmin but it only changes the field but no the internal working of the UserAdmin and so then again we modify its internal working using the UserCreationForm and the UserChangeForm .
"""

class CustomUserAdmin(UserAdmin):
    add_form = CustomUserCreationForm
    form = CustomUserChangeForm
    model = CustomUser

    list_display = ('email', 'username', 'is_staff', 'is_active')
    ordering = ('email',)

    fieldsets = (
        (None, {'fields': ('email', 'username', 'password')}),
        ('Personal Info', {'fields': ('first_name', 'last_name')}),
        ('Permissions', {'fields': ('is_staff', 'is_superuser', 'is_active')}),
    )

    # UPDATED: We now use 'password1' and 'password2' here too
    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('email', 'username', 'password1', 'password2'),
        }),
    )


admin.site.register(CustomUser, CustomUserAdmin)