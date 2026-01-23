from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q, Count, Avg
from .models import Student, Department
from users.models import UserProfile


def check_student_access(user_profile, department_id=None):
    """
    Helper function to check if user has access to student data.
    Returns (has_access, error_message)
    """
    if not user_profile:
        return False, "User profile not found."
    
    if not user_profile.can_view_students():
        return False, "You don't have permission to view student data."
    
    # HOD can only access their own department
    if user_profile.role == UserProfile.Role.HOD and department_id:
        if str(user_profile.department_id) != str(department_id):
            return False, "You can only access your own department."
    
    return True, None


@login_required
def department_list(request):
    """View to display all departments - Entry point for Student Database"""
    # Get user profile and check permissions
    user_profile = UserProfile.get_by_email(request.user.email)
    
    # Check if user can manage students
    if not user_profile or not user_profile.can_manage_students():
        return render(request, 'students/access_denied.html', {
            'user_profile': user_profile,
            'user_name': user_profile.name if user_profile else request.user.username,
            'user_role': user_profile.role if user_profile else 'Unknown',
        })
    
    # If HOD, redirect directly to their department's batch list
    if user_profile.role == UserProfile.Role.HOD and user_profile.department_id:
        return redirect('students:batch_list', department_id=user_profile.department_id)
    
    # Get all active departments with student counts (for Principal/Dean)
    departments = Department.objects.filter(is_active=True)
    
    # Get student counts per department
    dept_data = []
    for dept in departments:
        student_count = Student.objects.filter(department_id=dept.id).count()
        batch_count = Student.objects.filter(department_id=dept.id).values('batch_year').distinct().count()
        dept_data.append({
            'department': dept,
            'student_count': student_count,
            'batch_count': batch_count,
        })
    
    context = {
        'departments': dept_data,
        'total_departments': departments.count(),
        'user_profile': user_profile,
        'user_name': user_profile.name if user_profile else request.user.username,
        'user_role': user_profile.role if user_profile else 'Unknown',
    }
    
    return render(request, 'students/department_list.html', context)


@login_required
def batch_list(request, department_id):
    """View to display batches for a specific department"""
    # Get user profile and check permissions
    user_profile = UserProfile.get_by_email(request.user.email)
    
    if not user_profile or not user_profile.can_manage_students():
        return render(request, 'students/access_denied.html', {
            'user_profile': user_profile,
            'user_name': user_profile.name if user_profile else request.user.username,
            'user_role': user_profile.role if user_profile else 'Unknown',
        })
    
    # HOD can only access their own department
    if user_profile.role == UserProfile.Role.HOD:
        if str(user_profile.department_id) != str(department_id):
            return render(request, 'students/access_denied.html', {
                'user_profile': user_profile,
                'user_name': user_profile.name if user_profile else request.user.username,
                'user_role': user_profile.role if user_profile else 'Unknown',
                'message': 'You can only access your own department.',
            })
    
    # Get department
    department = get_object_or_404(Department, id=department_id)
    
    # Get distinct batch years for this department with student counts
    batches_raw = Student.objects.filter(department_id=department_id).values('batch_year').annotate(
        student_count=Count('id')
    ).order_by('-batch_year')
    
    batches = []
    for batch in batches_raw:
        if batch['batch_year']:
            # Calculate male/female counts
            male_count = Student.objects.filter(
                department_id=department_id, 
                batch_year=batch['batch_year'],
                gender='MALE'
            ).count()
            female_count = Student.objects.filter(
                department_id=department_id, 
                batch_year=batch['batch_year'],
                gender='FEMALE'
            ).count()
            
            batches.append({
                'batch_year': batch['batch_year'],
                'student_count': batch['student_count'],
                'male_count': male_count,
                'female_count': female_count,
            })
    
    context = {
        'department': department,
        'batches': batches,
        'user_profile': user_profile,
        'user_name': user_profile.name if user_profile else request.user.username,
        'user_role': user_profile.role if user_profile else 'Unknown',
    }
    
    return render(request, 'students/batch_list.html', context)


@login_required
def student_list(request, department_id, batch_year):
    """View to display students for a specific department and batch"""
    # Get user profile and check permissions
    user_profile = UserProfile.get_by_email(request.user.email)
    
    if not user_profile or not user_profile.can_manage_students():
        return render(request, 'students/access_denied.html', {
            'user_profile': user_profile,
            'user_name': user_profile.name if user_profile else request.user.username,
            'user_role': user_profile.role if user_profile else 'Unknown',
        })
    
    # HOD can only access their own department
    if user_profile.role == UserProfile.Role.HOD:
        if str(user_profile.department_id) != str(department_id):
            return render(request, 'students/access_denied.html', {
                'user_profile': user_profile,
                'user_name': user_profile.name if user_profile else request.user.username,
                'user_role': user_profile.role if user_profile else 'Unknown',
                'message': 'You can only access your own department.',
            })
    
    # Get department
    department = get_object_or_404(Department, id=department_id)
    
    # Get students for this department and batch
    students = Student.objects.filter(
        department_id=department_id,
        batch_year=batch_year
    )
    
    # Search functionality
    search_query = request.GET.get('search', '')
    if search_query:
        students = students.filter(
            Q(student_name__icontains=search_query) |
            Q(roll_number__icontains=search_query) |
            Q(register_number__icontains=search_query) |
            Q(mobile_number__icontains=search_query)
        )
    
    # Filter by gender
    gender_filter = request.GET.get('gender', '')
    if gender_filter:
        students = students.filter(gender=gender_filter)
    
    # Filter by hosteller status
    hosteller_filter = request.GET.get('hosteller', '')
    if hosteller_filter:
        students = students.filter(hosteller=(hosteller_filter == 'true'))
    
    total_count = students.count()
    
    # Pagination
    paginator = Paginator(students, 20)
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)
    
    context = {
        'department': department,
        'batch_year': batch_year,
        'page_obj': page_obj,
        'students': page_obj,
        'total_count': total_count,
        'search_query': search_query,
        'gender_filter': gender_filter,
        'hosteller_filter': hosteller_filter,
        'user_profile': user_profile,
        'user_name': user_profile.name if user_profile else request.user.username,
        'user_role': user_profile.role if user_profile else 'Unknown',
    }
    
    return render(request, 'students/student_list.html', context)


@login_required
def student_detail(request, student_id):
    """View to display individual student details"""
    # Get user profile and check permissions
    user_profile = UserProfile.get_by_email(request.user.email)
    
    # Check if user can manage students
    if not user_profile or not user_profile.can_manage_students():
        return render(request, 'students/access_denied.html', {
            'user_profile': user_profile,
            'user_name': user_profile.name if user_profile else request.user.username,
            'user_role': user_profile.role if user_profile else 'Unknown',
        })
    
    student = get_object_or_404(Student, id=student_id)
    
    # HOD can only access students from their own department
    if user_profile.role == UserProfile.Role.HOD:
        if str(user_profile.department_id) != str(student.department_id):
            return render(request, 'students/access_denied.html', {
                'user_profile': user_profile,
                'user_name': user_profile.name if user_profile else request.user.username,
                'user_role': user_profile.role if user_profile else 'Unknown',
                'message': 'You can only access students from your own department.',
            })
    
    # Get department info
    department = None
    if student.department_id:
        try:
            department = Department.objects.get(id=student.department_id)
        except Department.DoesNotExist:
            pass
    
    context = {
        'student': student,
        'department': department,
        'user_profile': user_profile,
        'user_name': user_profile.name if user_profile else request.user.username,
        'can_edit': user_profile.can_edit_students() if user_profile else False,
    }
    
    return render(request, 'students/student_detail.html', context)


@login_required
def student_edit(request, student_id):
    """View to edit student details"""
    from django.db import connection
    from django.contrib import messages
    
    user_profile = UserProfile.get_by_email(request.user.email)
    
    # Check edit permission
    if not user_profile or not user_profile.can_edit_students():
        return render(request, 'students/access_denied.html', {
            'user_profile': user_profile,
            'user_name': user_profile.name if user_profile else request.user.username,
            'user_role': user_profile.role if user_profile else 'Unknown',
            'message': 'You do not have permission to edit student records.',
        })
    
    student = get_object_or_404(Student, id=student_id)
    
    # HOD can only edit students from their own department
    if user_profile.role == UserProfile.Role.HOD:
        if str(user_profile.department_id) != str(student.department_id):
            return render(request, 'students/access_denied.html', {
                'user_profile': user_profile,
                'user_name': user_profile.name if user_profile else request.user.username,
                'user_role': user_profile.role if user_profile else 'Unknown',
                'message': 'You can only edit students from your own department.',
            })
    
    department = None
    if student.department_id:
        try:
            department = Department.objects.get(id=student.department_id)
        except Department.DoesNotExist:
            pass
    
    departments = Department.objects.filter(is_active=True)
    
    if request.method == 'POST':
        # Get form data
        student_name = request.POST.get('student_name', '').strip()
        salutation = request.POST.get('salutation', '').strip() or None
        college_email = request.POST.get('college_email', '').strip() or None
        register_number = request.POST.get('register_number', '').strip()
        roll_number = request.POST.get('roll_number', '').strip()
        gender = request.POST.get('gender', '')
        blood_group = request.POST.get('blood_group', '').strip() or None
        mobile_number = request.POST.get('mobile_number', '').strip() or None
        district = request.POST.get('district', '').strip() or None
        date_of_birth = request.POST.get('date_of_birth', '') or None
        date_of_admission = request.POST.get('date_of_admission', '') or None
        academic_year_join = request.POST.get('academic_year_join', '').strip() or None
        course_type = request.POST.get('course_type', '') or None
        admission_quota = request.POST.get('admission_quota', '').strip() or None
        hosteller = request.POST.get('hosteller') == 'on'
        batch_year = request.POST.get('batch_year', '').strip() or None
        
        # Parent info
        father_name = request.POST.get('father_name', '').strip() or None
        father_occupation = request.POST.get('father_occupation', '').strip() or None
        mother_name = request.POST.get('mother_name', '').strip() or None
        mother_occupation = request.POST.get('mother_occupation', '').strip() or None
        
        # Additional info
        religion = request.POST.get('religion', '').strip() or None
        community = request.POST.get('community', '').strip() or None
        caste = request.POST.get('caste', '').strip() or None
        aadhaar_number = request.POST.get('aadhaar_number', '').strip() or None
        permanent_address = request.POST.get('permanent_address', '').strip() or None
        first_graduate = request.POST.get('first_graduate') == 'on'
        
        # Validation
        if not all([student_name, register_number, roll_number, gender]):
            messages.error(request, 'Please fill all required fields.')
            return redirect('students:student_edit', student_id=student_id)
        
        # Update in database using raw SQL (since managed=False)
        try:
            with connection.cursor() as cursor:
                cursor.execute("""
                    UPDATE students SET
                        student_name = %s, salutation = %s, college_email = %s,
                        register_number = %s, roll_number = %s, gender = %s,
                        blood_group = %s, mobile_number = %s, district = %s,
                        date_of_birth = %s, date_of_admission = %s, academic_year_join = %s,
                        course_type = %s, admission_quota = %s, hosteller = %s, is_hosteller = %s,
                        batch_year = %s, father_name = %s, father_occupation = %s,
                        mother_name = %s, mother_occupation = %s, religion = %s,
                        community = %s, caste = %s, aadhaar_number = %s,
                        permanent_address = %s, first_graduate = %s
                    WHERE id = %s
                """, [
                    student_name, salutation, college_email,
                    register_number, roll_number, gender,
                    blood_group, mobile_number, district,
                    date_of_birth, date_of_admission, academic_year_join,
                    course_type, admission_quota, hosteller, hosteller,
                    batch_year, father_name, father_occupation,
                    mother_name, mother_occupation, religion,
                    community, caste, aadhaar_number,
                    permanent_address, first_graduate,
                    str(student_id)
                ])
            
            messages.success(request, f'Student "{student_name}" updated successfully!')
            return redirect('students:student_detail', student_id=student_id)
        except Exception as e:
            messages.error(request, f'Error updating student: {str(e)}')
    
    context = {
        'student': student,
        'department': department,
        'departments': departments,
        'user_profile': user_profile,
        'user_name': user_profile.name if user_profile else request.user.username,
        'user_role': user_profile.role if user_profile else 'Unknown',
    }
    
    return render(request, 'students/student_edit.html', context)


@login_required
def student_add(request, department_id=None, batch_year=None):
    """View to add a new student"""
    from django.db import connection
    from django.contrib import messages
    import uuid
    
    user_profile = UserProfile.get_by_email(request.user.email)
    
    # Check add permission
    if not user_profile or not user_profile.can_add_students():
        return render(request, 'students/access_denied.html', {
            'user_profile': user_profile,
            'user_name': user_profile.name if user_profile else request.user.username,
            'user_role': user_profile.role if user_profile else 'Unknown',
            'message': 'You do not have permission to add students.',
        })
    
    # HOD can only add students to their own department
    if user_profile.role == UserProfile.Role.HOD:
        department_id = str(user_profile.department_id)
    
    departments = Department.objects.filter(is_active=True)
    
    if request.method == 'POST':
        # Get form data
        dept_id = request.POST.get('department_id', department_id)
        
        # HOD restriction
        if user_profile.role == UserProfile.Role.HOD and str(dept_id) != str(user_profile.department_id):
            messages.error(request, 'You can only add students to your own department.')
            return redirect('students:student_add')
        
        student_name = request.POST.get('student_name', '').strip()
        salutation = request.POST.get('salutation', '').strip() or None
        college_email = request.POST.get('college_email', '').strip() or None
        register_number = request.POST.get('register_number', '').strip()
        roll_number = request.POST.get('roll_number', '').strip()
        gender = request.POST.get('gender', '')
        blood_group = request.POST.get('blood_group', '').strip() or None
        mobile_number = request.POST.get('mobile_number', '').strip() or None
        district = request.POST.get('district', '').strip() or None
        date_of_birth = request.POST.get('date_of_birth', '') or None
        date_of_admission = request.POST.get('date_of_admission', '') or None
        academic_year_join = request.POST.get('academic_year_join', '').strip() or None
        course_type = request.POST.get('course_type', '') or None
        admission_quota = request.POST.get('admission_quota', '').strip() or None
        hosteller = request.POST.get('hosteller') == 'on'
        batch_year_val = request.POST.get('batch_year', batch_year or '').strip() or None
        
        # Parent info
        father_name = request.POST.get('father_name', '').strip() or None
        mother_name = request.POST.get('mother_name', '').strip() or None
        
        # Validation
        if not all([student_name, register_number, roll_number, gender, dept_id]):
            messages.error(request, 'Please fill all required fields.')
            return redirect('students:student_add')
        
        # Insert into database
        try:
            new_id = uuid.uuid4()
            with connection.cursor() as cursor:
                cursor.execute("""
                    INSERT INTO students (
                        id, institution_id, department_id, student_name, salutation,
                        college_email, register_number, roll_number, gender,
                        blood_group, mobile_number, district, date_of_birth,
                        date_of_admission, academic_year_join, course_type,
                        admission_quota, hosteller, is_hosteller, batch_year,
                        father_name, mother_name
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, [
                    str(new_id), str(user_profile.institution_id), dept_id,
                    student_name, salutation, college_email, register_number,
                    roll_number, gender, blood_group, mobile_number, district,
                    date_of_birth, date_of_admission, academic_year_join,
                    course_type, admission_quota, hosteller, hosteller,
                    batch_year_val, father_name, mother_name
                ])
            
            messages.success(request, f'Student "{student_name}" added successfully!')
            return redirect('students:student_detail', student_id=new_id)
        except Exception as e:
            messages.error(request, f'Error adding student: {str(e)}')
    
    context = {
        'department_id': department_id,
        'batch_year': batch_year,
        'departments': departments,
        'user_profile': user_profile,
        'user_name': user_profile.name if user_profile else request.user.username,
        'user_role': user_profile.role if user_profile else 'Unknown',
    }
    
    return render(request, 'students/student_add.html', context)


# ==================== ACADEMIC ANALYTICS VIEWS ====================

@login_required
def academic_analytics(request):
    """
    View for academic analytics dashboard.
    - Principal: All departments, sorted by department
    - Dean: All departments, sorted by batch
    - HOD: Redirected to their department's analytics
    """
    user_profile = UserProfile.get_by_email(request.user.email)
    
    if not user_profile or not user_profile.can_access_department_analytics():
        return render(request, 'students/access_denied.html', {
            'user_profile': user_profile,
            'user_name': user_profile.name if user_profile else request.user.username,
            'user_role': user_profile.role if user_profile else 'Unknown',
            'message': 'You do not have access to academic analytics.',
        })
    
    # HOD can only see their department's analytics
    if user_profile.role == UserProfile.Role.HOD:
        if user_profile.department_id:
            return redirect('students:department_analytics', department_id=user_profile.department_id)
        else:
            return render(request, 'students/access_denied.html', {
                'message': 'No department assigned to your profile.',
            })
    
    # Get analytics scope and ordering preference
    analytics_scope = user_profile.get_analytics_scope()
    order_by = user_profile.get_analytics_order_preference()
    
    # Get all departments with analytics
    departments = Department.objects.filter(is_active=True)
    
    analytics_data = []
    total_students = 0
    total_male = 0
    total_female = 0
    total_hostellers = 0
    
    for dept in departments:
        dept_students = Student.objects.filter(department_id=dept.id)
        student_count = dept_students.count()
        male_count = dept_students.filter(gender='MALE').count()
        female_count = dept_students.filter(gender='FEMALE').count()
        hosteller_count = dept_students.filter(hosteller=True).count()
        
        # Get batch-wise breakdown
        batches = dept_students.values('batch_year').annotate(
            count=Count('id')
        ).order_by('-batch_year')
        
        analytics_data.append({
            'department': dept,
            'student_count': student_count,
            'male_count': male_count,
            'female_count': female_count,
            'hosteller_count': hosteller_count,
            'day_scholar_count': student_count - hosteller_count,
            'batches': list(batches),
        })
        
        total_students += student_count
        total_male += male_count
        total_female += female_count
        total_hostellers += hosteller_count
    
    # Sort based on role preference
    if order_by == 'department':
        analytics_data.sort(key=lambda x: x['department'].name)
    elif order_by == 'batch':
        # Sort by total students descending for batch-focused view
        analytics_data.sort(key=lambda x: x['student_count'], reverse=True)
    
    # Get overall batch-wise statistics
    all_batches = Student.objects.values('batch_year').annotate(
        count=Count('id')
    ).order_by('-batch_year')
    
    context = {
        'user_profile': user_profile,
        'user_name': user_profile.name if user_profile else request.user.username,
        'user_role': user_profile.role if user_profile else 'Unknown',
        'analytics_data': analytics_data,
        'total_students': total_students,
        'total_male': total_male,
        'total_female': total_female,
        'total_hostellers': total_hostellers,
        'total_day_scholars': total_students - total_hostellers,
        'total_departments': len(analytics_data),
        'all_batches': list(all_batches),
        'order_by': order_by,
        'can_modify_schema': user_profile.can_modify_students_schema(),
    }
    
    return render(request, 'students/academic_analytics.html', context)


@login_required
def department_analytics(request, department_id):
    """
    View for department-specific academic analytics.
    - HOD: Can only access their own department
    - Principal/Dean: Can access any department
    """
    user_profile = UserProfile.get_by_email(request.user.email)
    
    if not user_profile or not user_profile.can_access_department_analytics():
        return render(request, 'students/access_denied.html', {
            'user_profile': user_profile,
            'user_name': user_profile.name if user_profile else request.user.username,
            'user_role': user_profile.role if user_profile else 'Unknown',
            'message': 'You do not have access to academic analytics.',
        })
    
    # HOD can only access their own department
    has_access, error_msg = check_student_access(user_profile, department_id)
    if not has_access:
        return render(request, 'students/access_denied.html', {
            'user_profile': user_profile,
            'user_name': user_profile.name if user_profile else request.user.username,
            'user_role': user_profile.role if user_profile else 'Unknown',
            'message': error_msg,
        })
    
    department = get_object_or_404(Department, id=department_id)
    students = Student.objects.filter(department_id=department_id)
    
    # Overall statistics
    total_students = students.count()
    male_count = students.filter(gender='MALE').count()
    female_count = students.filter(gender='FEMALE').count()
    hosteller_count = students.filter(hosteller=True).count()
    
    # Batch-wise breakdown
    batches_data = []
    batch_years = students.values('batch_year').distinct().order_by('-batch_year')
    
    for batch in batch_years:
        batch_year = batch['batch_year']
        if batch_year:
            batch_students = students.filter(batch_year=batch_year)
            batches_data.append({
                'batch_year': batch_year,
                'student_count': batch_students.count(),
                'male_count': batch_students.filter(gender='MALE').count(),
                'female_count': batch_students.filter(gender='FEMALE').count(),
                'hosteller_count': batch_students.filter(hosteller=True).count(),
                'day_scholar_count': batch_students.filter(hosteller=False).count(),
            })
    
    # Course type breakdown
    course_breakdown = students.values('course_type').annotate(
        count=Count('id')
    ).order_by('course_type')
    
    # Admission quota breakdown
    quota_breakdown = students.values('admission_quota').annotate(
        count=Count('id')
    ).order_by('admission_quota')
    
    context = {
        'user_profile': user_profile,
        'user_name': user_profile.name if user_profile else request.user.username,
        'user_role': user_profile.role if user_profile else 'Unknown',
        'department': department,
        'total_students': total_students,
        'male_count': male_count,
        'female_count': female_count,
        'hosteller_count': hosteller_count,
        'day_scholar_count': total_students - hosteller_count,
        'batches_data': batches_data,
        'course_breakdown': list(course_breakdown),
        'quota_breakdown': list(quota_breakdown),
        'can_modify_schema': user_profile.can_modify_students_schema(),
    }
    
    return render(request, 'students/department_analytics.html', context)
