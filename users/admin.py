from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib import messages
from django.http import HttpResponseRedirect
from django.urls import path, reverse
from django.shortcuts import render
from django import forms
from .models import CustomUser, UserProfile
from .forms import CustomUserCreationForm, CustomUserChangeForm
import bcrypt

"""
Admin Configuration for Academic Administrator

Role-based admin access:
- ADMIN: Full access to all users, can change passwords, modify all DB schemas
- PRINCIPAL: Can view users but cannot modify admin settings
- Others: Limited or no admin access

1. we create a DB and modified it using the AbstractUser

2.we only changed the DB looks,but not how they are created ,so now we modift the BaseUserManager within which we hard-code the login fields and the superuser fields

3.now we modify the admin page fields using the UserAdmin but it only changes the field but no the internal working of the UserAdmin and so then again we modify its internal working using the UserCreationForm and the UserChangeForm .
"""


class ChangePasswordForm(forms.Form):
    """Form for admin to change user's password"""
    new_password1 = forms.CharField(
        label="New password",
        widget=forms.PasswordInput(attrs={'class': 'vTextField'}),
        min_length=8,
    )
    new_password2 = forms.CharField(
        label="Confirm password",
        widget=forms.PasswordInput(attrs={'class': 'vTextField'}),
    )
    
    def clean(self):
        cleaned_data = super().clean()
        password1 = cleaned_data.get('new_password1')
        password2 = cleaned_data.get('new_password2')
        
        if password1 and password2 and password1 != password2:
            raise forms.ValidationError("Passwords don't match")
        return cleaned_data


class CustomUserAdmin(UserAdmin):
    add_form = CustomUserCreationForm
    form = CustomUserChangeForm
    model = CustomUser

    list_display = ('email', 'username', 'get_role', 'is_staff', 'is_active', 'is_superuser')
    list_filter = ('is_staff', 'is_active', 'is_superuser', 'groups')
    search_fields = ('email', 'username')
    ordering = ('email',)
    
    actions = ['activate_users', 'deactivate_users']

    fieldsets = (
        (None, {'fields': ('email', 'username', 'password')}),
        ('Personal Info', {'fields': ('first_name', 'last_name')}),
        ('Permissions', {'fields': ('is_staff', 'is_superuser', 'is_active', 'groups')}),
    )

    # UPDATED: We now use 'password1' and 'password2' here too
    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('email', 'username', 'password1', 'password2'),
        }),
    )
    
    def get_role(self, obj):
        """Get role from UserProfile"""
        profile = UserProfile.get_by_email(obj.email)
        return profile.role if profile else 'N/A'
    get_role.short_description = 'Role'
    
    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                '<int:user_id>/change-password/',
                self.admin_site.admin_view(self.change_user_password_view),
                name='users_customuser_change_password',
            ),
        ]
        return custom_urls + urls
    
    def change_user_password_view(self, request, user_id):
        """Admin view to change any user's password"""
        # Check if current user is admin
        current_profile = UserProfile.get_by_email(request.user.email)
        if not current_profile or not current_profile.can_manage_all_users():
            messages.error(request, "You don't have permission to change passwords.")
            return HttpResponseRedirect(reverse('admin:users_customuser_changelist'))
        
        try:
            user = CustomUser.objects.get(pk=user_id)
            user_profile = UserProfile.get_by_email(user.email)
        except CustomUser.DoesNotExist:
            messages.error(request, "User not found.")
            return HttpResponseRedirect(reverse('admin:users_customuser_changelist'))
        
        if request.method == 'POST':
            form = ChangePasswordForm(request.POST)
            if form.is_valid():
                new_password = form.cleaned_data['new_password1']
                
                # Update password in cloud DB (UserProfile)
                if user_profile:
                    # Hash the password using bcrypt
                    hashed = bcrypt.hashpw(
                        new_password.encode('utf-8'),
                        bcrypt.gensalt()
                    ).decode('utf-8')
                    
                    # Note: Since managed=False, we need to update directly
                    from django.db import connection
                    with connection.cursor() as cursor:
                        cursor.execute(
                            "UPDATE users SET password_hash = %s WHERE email = %s",
                            [hashed, user.email]
                        )
                    
                    messages.success(
                        request, 
                        f"Password changed successfully for {user.email}"
                    )
                else:
                    # For local-only users (like emergency admin)
                    user.set_password(new_password)
                    user.save()
                    messages.success(
                        request, 
                        f"Password changed successfully for {user.email} (local user)"
                    )
                
                return HttpResponseRedirect(reverse('admin:users_customuser_changelist'))
        else:
            form = ChangePasswordForm()
        
        context = {
            'form': form,
            'user': user,
            'title': f'Change Password for {user.email}',
            'opts': self.model._meta,
            'has_change_permission': True,
        }
        return render(request, 'admin/users/change_password.html', context)
    
    def activate_users(self, request, queryset):
        """Bulk activate users"""
        queryset.update(is_active=True)
        messages.success(request, f"{queryset.count()} users activated.")
    activate_users.short_description = "Activate selected users"
    
    def deactivate_users(self, request, queryset):
        """Bulk deactivate users"""
        queryset.update(is_active=False)
        messages.success(request, f"{queryset.count()} users deactivated.")
    deactivate_users.short_description = "Deactivate selected users"
    
    def has_change_permission(self, request, obj=None):
        """Only Admin can change user details"""
        profile = UserProfile.get_by_email(request.user.email)
        if profile and profile.can_manage_all_users():
            return True
        # Allow users to change their own profile
        if obj and obj.email == request.user.email:
            return True
        return request.user.is_superuser
    
    def has_delete_permission(self, request, obj=None):
        """Only Admin can delete users"""
        profile = UserProfile.get_by_email(request.user.email)
        if profile and profile.can_manage_all_users():
            return True
        return request.user.is_superuser


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    """
    Read-only admin view for UserProfile (cloud DB).
    Admin can view all users and their roles from the cloud database.
    """
    list_display = ('full_name', 'email', 'role', 'department_id', 'is_active', 'last_login')
    list_filter = ('role', 'is_active')
    search_fields = ('full_name', 'email')
    ordering = ('role', 'full_name')
    readonly_fields = ('id', 'institution_id', 'department_id', 'full_name', 'email', 
                       'password_hash', 'role', 'is_active', 'last_login', 'created_at')
    
    def has_add_permission(self, request):
        """Cannot add users through Django admin - use cloud DB"""
        return False
    
    def has_delete_permission(self, request, obj=None):
        """Cannot delete users through Django admin - use cloud DB"""
        return False
    
    def has_change_permission(self, request, obj=None):
        """Read-only view"""
        return False


admin.site.register(CustomUser, CustomUserAdmin)