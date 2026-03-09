from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db import connection
from .models import UserProfile, CustomUser
from students.models import Department
import bcrypt
import uuid


@login_required
def user_management(request):
    """Admin dashboard for managing users"""
    user_profile = UserProfile.get_by_email(request.user.email)
    
    # Only ADMIN can access user management
    if not user_profile or not user_profile.can_add_users():
        return render(request, 'users/access_denied.html', {
            'user_profile': user_profile,
            'user_name': user_profile.name if user_profile else request.user.username,
            'message': 'Only administrators can manage users.'
        })
    
    # Get all users from cloud DB
    users = UserProfile.objects.all().order_by('role', 'full_name')
    departments = Department.objects.filter(is_active=True)
    
    context = {
        'users': users,
        'departments': departments,
        'user_profile': user_profile,
        'user_name': user_profile.name,
        'user_role': user_profile.role,
        'roles': UserProfile.Role.choices,
    }
    return render(request, 'users/user_management.html', context)


@login_required
def add_user(request):
    """Add a new user to the system"""
    user_profile = UserProfile.get_by_email(request.user.email)
    
    if not user_profile or not user_profile.can_add_users():
        messages.error(request, 'Only administrators can add users.')
        return redirect('users:user_management')
    
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        email = request.POST.get('email', '').strip().lower()
        password = request.POST.get('password', '')
        role = request.POST.get('role', '')
        department_id = request.POST.get('department_id', '') or None
        
        # Validation
        if not all([name, email, password, role]):
            messages.error(request, 'Please fill all required fields.')
            return redirect('users:user_management')
        
        # Check if email already exists
        if UserProfile.objects.filter(email=email).exists():
            messages.error(request, f'A user with email {email} already exists.')
            return redirect('users:user_management')
        
        # Hash the password
        password_hash = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
        
        # Get institution_id from current admin
        institution_id = str(user_profile.institution_id)
        
        # Insert into cloud DB
        try:
            new_id = uuid.uuid4()
            # derive a username from email local-part to satisfy existing DB NOT NULL constraint
            username = email.split('@')[0]
            with connection.cursor() as cursor:
                cursor.execute("""
                    INSERT INTO users (id, institution_id, department_id, username, full_name, email, password_hash, role, is_active)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, TRUE)
                """, [str(new_id), institution_id, department_id, username, name, email, password_hash, role])
            
            # Also create Django user for login
            CustomUser.objects.create_user(
                email=email,
                password=password,
                username=email.split('@')[0]
            )
            
            messages.success(request, f'User "{name}" ({role}) added successfully!')
        except Exception as e:
            messages.error(request, f'Error adding user: {str(e)}')
        
        return redirect('users:user_management')
    
    return redirect('users:user_management')


@login_required
def edit_user(request, user_id):
    """Edit an existing user"""
    user_profile = UserProfile.get_by_email(request.user.email)
    
    if not user_profile or not user_profile.can_add_users():
        messages.error(request, 'Only administrators can edit users.')
        return redirect('users:user_management')
    
    try:
        target_user = UserProfile.objects.get(id=user_id)
    except UserProfile.DoesNotExist:
        messages.error(request, 'User not found.')
        return redirect('users:user_management')
    
    departments = Department.objects.filter(is_active=True)
    
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        email = request.POST.get('email', '').strip().lower()
        role = request.POST.get('role', '')
        department_id = request.POST.get('department_id', '') or None
        is_active = request.POST.get('is_active') == 'on'
        
        if not all([name, email, role]):
            messages.error(request, 'Please fill all required fields.')
            return redirect('users:edit_user', user_id=user_id)
        
        # Check if email already exists (for different user)
        existing = UserProfile.objects.filter(email=email).exclude(id=user_id).first()
        if existing:
            messages.error(request, f'Email {email} is already used by another user.')
            return redirect('users:edit_user', user_id=user_id)
        
        # Update in cloud DB using raw SQL
        try:
            with connection.cursor() as cursor:
                cursor.execute("""
                    UPDATE users 
                    SET full_name = %s, email = %s, role = %s, department_id = %s, is_active = %s
                    WHERE id = %s
                """, [name, email, role, department_id, is_active, str(user_id)])
            
            # Update Django user email if changed
            if target_user.email != email:
                try:
                    django_user = CustomUser.objects.get(email=target_user.email)
                    django_user.email = email
                    django_user.save()
                except CustomUser.DoesNotExist:
                    pass
            
            messages.success(request, f'User "{name}" updated successfully!')
        except Exception as e:
            messages.error(request, f'Error updating user: {str(e)}')
        
        return redirect('users:user_management')
    
    context = {
        'target_user': target_user,
        'departments': departments,
        'user_profile': user_profile,
        'user_name': user_profile.name,
        'user_role': user_profile.role,
        'roles': UserProfile.Role.choices,
    }
    return render(request, 'users/edit_user.html', context)


@login_required
def change_password(request, user_id):
    """Change a user's password"""
    user_profile = UserProfile.get_by_email(request.user.email)
    
    if not user_profile or not user_profile.can_add_users():
        messages.error(request, 'Only administrators can change passwords.')
        return redirect('users:user_management')
    
    try:
        target_user = UserProfile.objects.get(id=user_id)
    except UserProfile.DoesNotExist:
        messages.error(request, 'User not found.')
        return redirect('users:user_management')
    
    if request.method == 'POST':
        new_password = request.POST.get('new_password', '')
        confirm_password = request.POST.get('confirm_password', '')
        
        if not new_password:
            messages.error(request, 'Please enter a new password.')
            return redirect('users:user_management')
        
        if new_password != confirm_password:
            messages.error(request, 'Passwords do not match.')
            return redirect('users:user_management')
        
        if len(new_password) < 8:
            messages.error(request, 'Password must be at least 8 characters.')
            return redirect('users:user_management')
        
        # Hash the new password
        password_hash = bcrypt.hashpw(new_password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
        
        try:
            # Update in cloud DB
            with connection.cursor() as cursor:
                cursor.execute("""
                    UPDATE users SET password_hash = %s WHERE id = %s
                """, [password_hash, str(user_id)])
            
            # Update Django user password
            try:
                django_user = CustomUser.objects.get(email=target_user.email)
                django_user.set_password(new_password)
                django_user.save()
            except CustomUser.DoesNotExist:
                pass
            
            messages.success(request, f'Password changed successfully for "{target_user.name}"!')
        except Exception as e:
            messages.error(request, f'Error changing password: {str(e)}')
        
        return redirect('users:user_management')
    
    return redirect('users:user_management')


@login_required
def delete_user(request, user_id):
    """Delete a user from the system"""
    user_profile = UserProfile.get_by_email(request.user.email)
    
    if not user_profile or not user_profile.can_add_users():
        messages.error(request, 'Only administrators can delete users.')
        return redirect('users:user_management')
    
    try:
        target_user = UserProfile.objects.get(id=user_id)
    except UserProfile.DoesNotExist:
        messages.error(request, 'User not found.')
        return redirect('users:user_management')
    
    # Prevent deleting yourself
    if target_user.email == user_profile.email:
        messages.error(request, 'You cannot delete your own account.')
        return redirect('users:user_management')
    
    if request.method == 'POST':
        try:
            # Delete from cloud DB
            with connection.cursor() as cursor:
                cursor.execute("DELETE FROM users WHERE id = %s", [str(user_id)])
            
            # Delete Django user
            try:
                django_user = CustomUser.objects.get(email=target_user.email)
                django_user.delete()
            except CustomUser.DoesNotExist:
                pass
            
            messages.success(request, f'User "{target_user.name}" deleted successfully!')
        except Exception as e:
            messages.error(request, f'Error deleting user: {str(e)}')
    
    return redirect('users:user_management')


# ============================================
# DEPARTMENT MANAGEMENT VIEWS
# ============================================

@login_required
def department_management(request):
    """Admin dashboard for managing departments"""
    user_profile = UserProfile.get_by_email(request.user.email)
    
    # Only ADMIN can access department management
    if not user_profile or not user_profile.can_add_users():
        return render(request, 'users/access_denied.html', {
            'user_profile': user_profile,
            'user_name': user_profile.name if user_profile else request.user.username,
            'message': 'Only administrators can manage departments.'
        })
    
    # Get all departments
    departments = Department.objects.all().order_by('name')
    
    context = {
        'departments': departments,
        'user_profile': user_profile,
        'user_name': user_profile.name,
        'user_role': user_profile.role,
    }
    return render(request, 'users/department_management.html', context)


@login_required
def add_department(request):
    """Add a new department"""
    user_profile = UserProfile.get_by_email(request.user.email)
    
    if not user_profile or not user_profile.can_add_users():
        messages.error(request, 'Only administrators can add departments.')
        return redirect('users:department_management')
    
    if request.method == 'POST':
        name = request.POST.get('name', '').strip().upper()
        full_name = request.POST.get('full_name', '').strip()
        
        if not name or not full_name:
            messages.error(request, 'Department name and full name are required.')
            return redirect('users:department_management')
        
        try:
            # Insert into cloud DB
            with connection.cursor() as cursor:
                dept_id = uuid.uuid4()
                cursor.execute("""
                    INSERT INTO departments (id, name, full_name, is_active, created_at)
                    VALUES (%s, %s, %s, %s, NOW())
                """, [str(dept_id), name, full_name, True])
            
            messages.success(request, f'Department "{name}" added successfully!')
        except Exception as e:
            messages.error(request, f'Error adding department: {str(e)}')
    
    return redirect('users:department_management')


@login_required
def edit_department(request, dept_id):
    """Edit an existing department"""
    user_profile = UserProfile.get_by_email(request.user.email)
    
    if not user_profile or not user_profile.can_add_users():
        messages.error(request, 'Only administrators can edit departments.')
        return redirect('users:department_management')
    
    try:
        department = Department.objects.get(id=dept_id)
    except Department.DoesNotExist:
        messages.error(request, 'Department not found.')
        return redirect('users:department_management')
    
    if request.method == 'POST':
        name = request.POST.get('name', '').strip().upper()
        full_name = request.POST.get('full_name', '').strip()
        is_active = request.POST.get('is_active') == 'on'
        
        if not name or not full_name:
            messages.error(request, 'Department name and full name are required.')
            return redirect('users:department_management')
        
        try:
            # Update in cloud DB
            with connection.cursor() as cursor:
                cursor.execute("""
                    UPDATE departments 
                    SET name = %s, full_name = %s, is_active = %s
                    WHERE id = %s
                """, [name, full_name, is_active, str(dept_id)])
            
            messages.success(request, f'Department "{name}" updated successfully!')
        except Exception as e:
            messages.error(request, f'Error updating department: {str(e)}')
    
    return redirect('users:department_management')


@login_required
def delete_department(request, dept_id):
    """Delete a department (or deactivate it if it has students/staff)"""
    user_profile = UserProfile.get_by_email(request.user.email)
    
    if not user_profile or not user_profile.can_add_users():
        messages.error(request, 'Only administrators can delete departments.')
        return redirect('users:department_management')
    
    try:
        department = Department.objects.get(id=dept_id)
    except Department.DoesNotExist:
        messages.error(request, 'Department not found.')
        return redirect('users:department_management')
    
    if request.method == 'POST':
        try:
            # Check if department has students or staff
            with connection.cursor() as cursor:
                cursor.execute("""
                    SELECT 
                        (SELECT COUNT(*) FROM students WHERE department_id = %s) as student_count,
                        (SELECT COUNT(*) FROM staff WHERE department_id = %s) as staff_count
                """, [str(dept_id), str(dept_id)])
                result = cursor.fetchone()
                student_count, staff_count = result[0], result[1]
            
            if student_count > 0 or staff_count > 0:
                # Deactivate instead of delete
                with connection.cursor() as cursor:
                    cursor.execute("""
                        UPDATE departments SET is_active = false WHERE id = %s
                    """, [str(dept_id)])
                messages.warning(request, 
                    f'Department "{department.name}" has {student_count} students and {staff_count} staff members. '
                    f'It has been deactivated instead of deleted.')
            else:
                # Safe to delete
                with connection.cursor() as cursor:
                    cursor.execute("DELETE FROM departments WHERE id = %s", [str(dept_id)])
                messages.success(request, f'Department "{department.name}" deleted successfully!')
        except Exception as e:
            messages.error(request, f'Error deleting department: {str(e)}')
    
    return redirect('users:department_management')

