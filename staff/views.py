from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q, Count
from django.db import connection
from django.contrib import messages
from .models import Staff
from students.models import Department
from users.models import UserProfile
import uuid


@login_required
def department_list(request):
    """View to display all departments - Entry point for Staff Database"""
    user_profile = UserProfile.get_by_email(request.user.email)
    
    # Check if user can view staff
    if not user_profile or not user_profile.can_view_staff():
        return render(request, 'staff/access_denied.html', {
            'user_profile': user_profile,
            'user_name': user_profile.name if user_profile else request.user.username,
            'user_role': user_profile.role if user_profile else 'Unknown',
        })
    
    # If HOD, redirect directly to their department's staff list
    if user_profile.role == UserProfile.Role.HOD and user_profile.department_id:
        return redirect('staff:staff_list', department_id=user_profile.department_id)
    
    # Get all active departments with staff counts
    departments = Department.objects.filter(is_active=True)
    
    dept_data = []
    for dept in departments:
        staff_count = Staff.objects.filter(department_id=dept.id, is_active=True).count()
        dept_data.append({
            'department': dept,
            'staff_count': staff_count,
        })
    
    context = {
        'departments': dept_data,
        'total_departments': departments.count(),
        'user_profile': user_profile,
        'user_name': user_profile.name if user_profile else request.user.username,
        'user_role': user_profile.role if user_profile else 'Unknown',
        'can_add': user_profile.can_add_staff() if user_profile else False,
    }
    
    return render(request, 'staff/department_list.html', context)


@login_required
def staff_list(request, department_id):
    """View to display staff for a specific department"""
    user_profile = UserProfile.get_by_email(request.user.email)
    
    if not user_profile or not user_profile.can_view_staff():
        return render(request, 'staff/access_denied.html', {
            'user_profile': user_profile,
            'user_name': user_profile.name if user_profile else request.user.username,
            'user_role': user_profile.role if user_profile else 'Unknown',
        })
    
    # HOD can only access their own department
    if user_profile.role == UserProfile.Role.HOD:
        if str(user_profile.department_id) != str(department_id):
            return render(request, 'staff/access_denied.html', {
                'user_profile': user_profile,
                'user_name': user_profile.name if user_profile else request.user.username,
                'user_role': user_profile.role if user_profile else 'Unknown',
                'message': 'You can only access your own department.',
            })
    
    department = get_object_or_404(Department, id=department_id)
    
    # Get staff for this department
    staff_members = Staff.objects.filter(department_id=department_id, is_active=True)
    
    # Search functionality
    search_query = request.GET.get('search', '')
    if search_query:
        staff_members = staff_members.filter(
            Q(name__icontains=search_query) |
            Q(staff_code__icontains=search_query) |
            Q(designation__icontains=search_query) |
            Q(official_email__icontains=search_query)
        )
    
    # Filter by designation
    designation_filter = request.GET.get('designation', '')
    if designation_filter:
        staff_members = staff_members.filter(designation__icontains=designation_filter)
    
    total_count = staff_members.count()
    
    # Pagination
    paginator = Paginator(staff_members, 20)
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)
    
    # Get unique designations for filter dropdown
    designations = Staff.objects.filter(
        department_id=department_id, 
        is_active=True
    ).values_list('designation', flat=True).distinct()
    designations = [d for d in designations if d]
    
    context = {
        'department': department,
        'page_obj': page_obj,
        'staff_members': page_obj,
        'total_count': total_count,
        'search_query': search_query,
        'designation_filter': designation_filter,
        'designations': designations,
        'user_profile': user_profile,
        'user_name': user_profile.name if user_profile else request.user.username,
        'user_role': user_profile.role if user_profile else 'Unknown',
        'can_add': user_profile.can_add_staff() if user_profile else False,
        'can_edit': user_profile.can_edit_staff() if user_profile else False,
    }
    
    return render(request, 'staff/staff_list.html', context)


@login_required
def staff_detail(request, staff_id):
    """View to display individual staff details"""
    user_profile = UserProfile.get_by_email(request.user.email)
    
    if not user_profile or not user_profile.can_view_staff():
        return render(request, 'staff/access_denied.html', {
            'user_profile': user_profile,
            'user_name': user_profile.name if user_profile else request.user.username,
            'user_role': user_profile.role if user_profile else 'Unknown',
        })
    
    staff = get_object_or_404(Staff, id=staff_id)
    
    # HOD can only access staff from their own department
    if user_profile.role == UserProfile.Role.HOD:
        if str(user_profile.department_id) != str(staff.department_id):
            return render(request, 'staff/access_denied.html', {
                'user_profile': user_profile,
                'user_name': user_profile.name if user_profile else request.user.username,
                'user_role': user_profile.role if user_profile else 'Unknown',
                'message': 'You can only access staff from your own department.',
            })
    
    # Get department info
    department = None
    if staff.department_id:
        try:
            department = Department.objects.get(id=staff.department_id)
        except Department.DoesNotExist:
            pass
    
    context = {
        'staff': staff,
        'department': department,
        'user_profile': user_profile,
        'user_name': user_profile.name if user_profile else request.user.username,
        'user_role': user_profile.role if user_profile else 'Unknown',
        'can_edit': user_profile.can_edit_staff() if user_profile else False,
    }
    
    return render(request, 'staff/staff_detail.html', context)


@login_required
def staff_add(request, department_id=None):
    """View to add new staff - ADMIN only"""
    user_profile = UserProfile.get_by_email(request.user.email)
    
    if not user_profile or not user_profile.can_add_staff():
        return render(request, 'staff/access_denied.html', {
            'user_profile': user_profile,
            'user_name': user_profile.name if user_profile else request.user.username,
            'user_role': user_profile.role if user_profile else 'Unknown',
            'message': 'Only administrators can add new staff.',
        })
    
    departments = Department.objects.filter(is_active=True)
    
    if request.method == 'POST':
        try:
            staff_id = uuid.uuid4()
            institution_id = 'a9ec9892-fe62-45ad-9f91-eb02c75e56a6'  # Your institution ID
            
            # Get form data
            dept_id = request.POST.get('department_id')
            salutation = request.POST.get('salutation', '')
            name = request.POST.get('name', '')
            staff_code = request.POST.get('staff_code', '')
            designation = request.POST.get('designation', '')
            qualification = request.POST.get('qualification', '')
            official_email = request.POST.get('official_email', '')
            date_of_join = request.POST.get('date_of_join') or None
            
            with connection.cursor() as cursor:
                cursor.execute("""
                    INSERT INTO staff (
                        id, institution_id, department_id, salutation, name, 
                        staff_code, designation, qualification, official_email, 
                        date_of_join, is_active, created_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                """, [
                    str(staff_id), institution_id, dept_id or None, salutation, name,
                    staff_code, designation, qualification, official_email,
                    date_of_join, True
                ])
            
            messages.success(request, f'Staff member "{name}" added successfully!')
            return redirect('staff:staff_list', department_id=dept_id)
            
        except Exception as e:
            messages.error(request, f'Error adding staff: {str(e)}')
    
    context = {
        'departments': departments,
        'selected_department': department_id,
        'user_profile': user_profile,
        'user_name': user_profile.name,
        'user_role': user_profile.role,
    }
    
    return render(request, 'staff/staff_add.html', context)


@login_required
def staff_edit(request, staff_id):
    """View to edit staff details - ADMIN only"""
    user_profile = UserProfile.get_by_email(request.user.email)
    
    if not user_profile or not user_profile.can_edit_staff():
        return render(request, 'staff/access_denied.html', {
            'user_profile': user_profile,
            'user_name': user_profile.name if user_profile else request.user.username,
            'user_role': user_profile.role if user_profile else 'Unknown',
            'message': 'Only administrators can edit staff records.',
        })
    
    staff = get_object_or_404(Staff, id=staff_id)
    departments = Department.objects.filter(is_active=True)
    
    # Get current department
    department = None
    if staff.department_id:
        try:
            department = Department.objects.get(id=staff.department_id)
        except Department.DoesNotExist:
            pass
    
    if request.method == 'POST':
        try:
            # Get form data
            dept_id = request.POST.get('department_id')
            salutation = request.POST.get('salutation', '')
            name = request.POST.get('name', '')
            staff_code = request.POST.get('staff_code', '')
            designation = request.POST.get('designation', '')
            qualification = request.POST.get('qualification', '')
            official_email = request.POST.get('official_email', '')
            date_of_join = request.POST.get('date_of_join') or None
            is_active = request.POST.get('is_active') == 'on'
            
            with connection.cursor() as cursor:
                cursor.execute("""
                    UPDATE staff SET
                        department_id = %s,
                        salutation = %s,
                        name = %s,
                        staff_code = %s,
                        designation = %s,
                        qualification = %s,
                        official_email = %s,
                        date_of_join = %s,
                        is_active = %s
                    WHERE id = %s
                """, [
                    dept_id or None, salutation, name, staff_code,
                    designation, qualification, official_email,
                    date_of_join, is_active, str(staff_id)
                ])
            
            messages.success(request, f'Staff member "{name}" updated successfully!')
            return redirect('staff:staff_detail', staff_id=staff_id)
            
        except Exception as e:
            messages.error(request, f'Error updating staff: {str(e)}')
    
    context = {
        'staff': staff,
        'department': department,
        'departments': departments,
        'user_profile': user_profile,
        'user_name': user_profile.name,
        'user_role': user_profile.role,
    }
    
    return render(request, 'staff/staff_edit.html', context)


@login_required
def staff_delete(request, staff_id):
    """View to delete/deactivate staff - ADMIN only"""
    user_profile = UserProfile.get_by_email(request.user.email)
    
    if not user_profile or not user_profile.can_delete_staff():
        return render(request, 'staff/access_denied.html', {
            'user_profile': user_profile,
            'user_name': user_profile.name if user_profile else request.user.username,
            'user_role': user_profile.role if user_profile else 'Unknown',
            'message': 'Only administrators can delete staff records.',
        })
    
    staff = get_object_or_404(Staff, id=staff_id)
    department_id = staff.department_id
    
    if request.method == 'POST':
        try:
            # Soft delete - set is_active to False
            with connection.cursor() as cursor:
                cursor.execute("""
                    UPDATE staff SET is_active = FALSE WHERE id = %s
                """, [str(staff_id)])
            
            messages.success(request, f'Staff member "{staff.name}" has been deactivated.')
            return redirect('staff:staff_list', department_id=department_id)
            
        except Exception as e:
            messages.error(request, f'Error deleting staff: {str(e)}')
            return redirect('staff:staff_detail', staff_id=staff_id)
    
    return redirect('staff:staff_detail', staff_id=staff_id)
