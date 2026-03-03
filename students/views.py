import json
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Sum, F, Q, Count
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt, ensure_csrf_cookie
from .models import Student, Department, ProgramSemester, Subject, SubjectResult, SemesterSummary, EndSemesterResult
from users.models import UserProfile


def recompute_semester_summary(program_semester, department_id=None):
    """
    Recompute SGPA and arrears for all students in a program semester.
    Uses EndSemesterResult data (primary) with fallback to SubjectResult.
    """
    from .models import Student, Subject, SubjectResult, SemesterSummary, EndSemesterResult
    
    # If department_id not provided, get it from first student in the batch
    if department_id is None:
        first_student = Student.objects.filter(
            academic_year_joining=program_semester.batch_year,
            is_active=True
        ).first()
        if not first_student:
            return  # No students in this batch
        department_id = first_student.department_id
    
    students = Student.objects.filter(
        department_id=department_id,
        academic_year_joining=program_semester.batch_year,
        is_active=True
    )
    
    subjects = Subject.objects.filter(semester=program_semester.semester)
    
    for student in students:
        # Try EndSemesterResult first (primary source for SGPA/arrears)
        end_results = EndSemesterResult.objects.filter(
            student=student,
            subject__in=subjects
        ).select_related('subject')
        
        if end_results.exists():
            # Calculate arrears from EndSemesterResult
            arrears = end_results.filter(
                Q(grade='U') | Q(result_status='FAIL') | Q(grade__isnull=True)
            ).count()
            
            # Calculate SGPA from EndSemesterResult
            valid_results = end_results.exclude(
                grade__isnull=True
            ).exclude(grade='U').exclude(result_status='FAIL')
            
            if valid_results.exists():
                total_quality_points = sum(
                    (float(result.grade_points) if result.grade_points else 0) * result.subject.credits
                    for result in valid_results
                )
                total_credits = sum(result.subject.credits for result in valid_results)
                sgpa = total_quality_points / total_credits if total_credits > 0 else None
            else:
                sgpa = None
                total_credits = 0
        else:
            # Fallback to SubjectResult (legacy)
            results = SubjectResult.objects.filter(
                student=student,
                subject__in=subjects
            ).select_related('subject')
            
            arrears = results.filter(
                Q(grade='U') | Q(grade__isnull=True)
            ).count()
            
            valid_results = results.exclude(grade__isnull=True).exclude(grade='U')
            if valid_results.exists():
                total_quality_points = sum(
                    (result.grade_points or 0) * result.subject.credits
                    for result in valid_results
                )
                total_credits = sum(result.subject.credits for result in valid_results)
                sgpa = total_quality_points / total_credits if total_credits > 0 else None
            else:
                sgpa = None
                total_credits = 0
        
        # Update or create semester summary
        SemesterSummary.objects.update_or_create(
            student=student,
            program_semester=program_semester,
            defaults={
                'sgpa': sgpa,
                'total_credits': total_credits,
                'earned_credits': total_credits,
                'arrear_count': arrears,
            }
        )


@login_required


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
        batch_count = Student.objects.filter(department_id=dept.id).values('academic_year_joining').distinct().count()
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
    batches_raw = Student.objects.filter(department_id=department_id).values('academic_year_joining').annotate(
        student_count=Count('id')
    ).order_by('-academic_year_joining')
    
    batches = []
    for batch in batches_raw:
        if batch['academic_year_joining']:
            # Calculate male/female counts
            male_count = Student.objects.filter(
                department_id=department_id, 
                academic_year_joining=batch['academic_year_joining'],
                gender='MALE'
            ).count()
            female_count = Student.objects.filter(
                department_id=department_id, 
                academic_year_joining=batch['academic_year_joining'],
                gender='FEMALE'
            ).count()
            
            batches.append({
                'batch_year': batch['academic_year_joining'],
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
        academic_year_joining=batch_year
    )
    
    # Search functionality
    search_query = request.GET.get('search', '')
    if search_query:
        students = students.filter(
            Q(student_name__icontains=search_query) |
            Q(roll_number__icontains=search_query) |
            Q(registration_number__icontains=search_query) |
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
    
    # Pagination - wrapped in try/except to handle bad date data in DB
    try:
        paginator = Paginator(students, 20)
        page_number = request.GET.get('page', 1)
        page_obj = paginator.get_page(page_number)
    except (ValueError, OverflowError) as e:
        # Bad date data in DB can cause "year XXXXX is out of range"
        # Fall back to raw SQL with dates cast to text
        from django.db import connection
        messages.warning(request, f'Some records have invalid date values: {e}')
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE students SET date_of_admission = NULL WHERE EXTRACT(YEAR FROM date_of_admission) > 9999"
            )
            cursor.execute(
                "UPDATE students SET date_of_birth = NULL WHERE EXTRACT(YEAR FROM date_of_birth) > 9999"
            )
        # Retry after fixing
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
        'batch_year': student.academic_year_joining,
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
        email_id = request.POST.get('college_email', '').strip() or request.POST.get('email_id', '').strip() or None
        registration_number = request.POST.get('register_number', '').strip() or request.POST.get('registration_number', '').strip() or None
        roll_number = request.POST.get('roll_number', '').strip()
        gender = request.POST.get('gender', '')
        blood_group = request.POST.get('blood_group', '').strip() or None
        mobile_number = request.POST.get('mobile_number', '').strip() or None
        district = request.POST.get('district', '').strip() or None
        date_of_birth = request.POST.get('date_of_birth', '') or None
        date_of_admission = request.POST.get('date_of_admission', '') or None
        academic_year_joining = request.POST.get('academic_year_join', '').strip() or request.POST.get('academic_year_joining', '').strip() or None
        mq_gq = request.POST.get('admission_quota', '').strip() or request.POST.get('mq_gq', '').strip() or None
        hosteller = request.POST.get('hosteller') == 'on'
        branch_specialization = request.POST.get('branch_specialization', '').strip() or None
        
        # Parent info
        father_name = request.POST.get('father_name', '').strip() or None
        mother_name = request.POST.get('mother_name', '').strip() or None
        
        # Additional info
        religion = request.POST.get('religion', '').strip() or None
        community = request.POST.get('community', '').strip() or None
        caste = request.POST.get('caste', '').strip() or None
        aadhaar_number = request.POST.get('aadhaar_number', '').strip() or None
        permanent_address = request.POST.get('permanent_address', '').strip() or None
        is_first_graduate = request.POST.get('first_graduate') == 'on' or request.POST.get('is_first_graduate') == 'on'
        
        # Validation
        if not all([student_name, roll_number, gender]):
            messages.error(request, 'Please fill all required fields.')
            return redirect('students:student_edit', student_id=student_id)
        
        # Update in database using raw SQL (since managed=False)
        try:
            with connection.cursor() as cursor:
                cursor.execute("""
                    UPDATE students SET
                        student_name = %s, email_id = %s,
                        registration_number = %s, roll_number = %s, gender = %s,
                        blood_group = %s, mobile_number = %s, district = %s,
                        date_of_birth = %s, date_of_admission = %s, academic_year_joining = %s,
                        mq_gq = %s, hosteller = %s,
                        branch_specialization = %s, father_name = %s,
                        mother_name = %s, religion = %s,
                        community = %s, caste = %s, aadhaar_number = %s,
                        permanent_address = %s, is_first_graduate = %s
                    WHERE id = %s
                """, [
                    student_name, email_id,
                    registration_number, roll_number, gender,
                    blood_group, mobile_number, district,
                    date_of_birth, date_of_admission, academic_year_joining,
                    mq_gq, hosteller,
                    branch_specialization, father_name,
                    mother_name, religion,
                    community, caste, aadhaar_number,
                    permanent_address, is_first_graduate,
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
        email_id = request.POST.get('college_email', '').strip() or request.POST.get('email_id', '').strip() or None
        registration_number = request.POST.get('register_number', '').strip() or request.POST.get('registration_number', '').strip() or None
        roll_number = request.POST.get('roll_number', '').strip()
        gender = request.POST.get('gender', '')
        blood_group = request.POST.get('blood_group', '').strip() or None
        mobile_number = request.POST.get('mobile_number', '').strip() or None
        district = request.POST.get('district', '').strip() or None
        date_of_birth = request.POST.get('date_of_birth', '') or None
        date_of_admission = request.POST.get('date_of_admission', '') or None
        academic_year_joining = request.POST.get('academic_year_join', '').strip() or request.POST.get('academic_year_joining', '').strip() or None
        mq_gq = request.POST.get('admission_quota', '').strip() or request.POST.get('mq_gq', '').strip() or None
        hosteller = request.POST.get('hosteller') == 'on'
        
        # Parent info
        father_name = request.POST.get('father_name', '').strip() or None
        mother_name = request.POST.get('mother_name', '').strip() or None
        
        # Validation
        if not all([student_name, roll_number, gender, dept_id]):
            messages.error(request, 'Please fill all required fields.')
            return redirect('students:student_add')
        
        # Insert into database
        try:
            new_id = uuid.uuid4()
            with connection.cursor() as cursor:
                cursor.execute("""
                    INSERT INTO students (
                        id, department_id, student_name,
                        email_id, registration_number, roll_number, gender,
                        blood_group, mobile_number, district, date_of_birth,
                        date_of_admission, academic_year_joining,
                        mq_gq, hosteller,
                        father_name, mother_name
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, [
                    str(new_id), dept_id,
                    student_name, email_id, registration_number,
                    roll_number, gender, blood_group, mobile_number, district,
                    date_of_birth, date_of_admission, academic_year_joining,
                    mq_gq, hosteller,
                    father_name, mother_name
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
            return redirect('students:analytics_department_batches', department_id=user_profile.department_id)
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
        batches = dept_students.values('academic_year_joining').annotate(
            count=Count('id')
        ).order_by('-academic_year_joining')
        
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
    all_batches = Student.objects.values('academic_year_joining').annotate(
        count=Count('id')
    ).order_by('-academic_year_joining')
    
    context = {
        'active_page': 'analytics',
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
        'can_modify_schema': user_profile.can_manage_students(),
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
    
    # Get distinct batch years for this department
    batch_qs = students.values("academic_year_joining").annotate(count=Count("id")).order_by("-academic_year_joining")
    batches_data = [
        {"batch_year": b["academic_year_joining"], "student_count": b["count"]}
        for b in batch_qs
    ]
    
    context = {
        'department': department,
        'batches': batches_data,
        'user_profile': user_profile,
        'user_name': user_profile.name if user_profile else request.user.username,
        'user_role': user_profile.role if user_profile else 'Unknown',
    }
    
    return render(request, 'students/department_analytics.html', context)


# ==================== DETAILED ANALYTICS HIERARCHY VIEWS ====================

@login_required
def analytics_department_batches(request, department_id):
    """
    View for showing active batches in a department for analytics.
    URL: /analytics/department/<department_id>/
    - Principal/Dean: Can access all departments
    - HOD: Can only access their own department
    """
    user_profile = UserProfile.get_by_email(request.user.email)

    if not user_profile or not user_profile.can_access_department_analytics():
        return render(request, 'students/access_denied.html', {
            'user_profile': user_profile,
            'user_name': user_profile.name if user_profile else request.user.username,
            'user_role': user_profile.role if user_profile else 'Unknown',
            'message': 'You do not have access to academic analytics.',
        })

    # Check department access: HOD can only access their own department
    # Principal/Dean can access all departments
    if user_profile.role == UserProfile.Role.HOD:
        if str(user_profile.department_id) != str(department_id):
            return render(request, 'students/access_denied.html', {
                'message': 'You can only access your own department.',
            })

    # Get department
    department = get_object_or_404(Department, id=department_id)

    # Get distinct batch years for this department with student counts
    # Same logic as batch_list view
    batches_raw = Student.objects.filter(department_id=department_id).values('academic_year_joining').annotate(
        student_count=Count('id')
    ).order_by('-academic_year_joining')

    batches = []
    for batch in batches_raw:
        if batch['academic_year_joining']:
            # Calculate male/female counts
            male_count = Student.objects.filter(
                department_id=department_id,
                academic_year_joining=batch['academic_year_joining'],
                gender='MALE'
            ).count()
            female_count = Student.objects.filter(
                department_id=department_id,
                academic_year_joining=batch['academic_year_joining'],
                gender='FEMALE'
            ).count()

            batches.append({
                'batch_year': batch['academic_year_joining'],
                'student_count': batch['student_count'],
                'male_count': male_count,
                'female_count': female_count,
            })

    context = {
        'active_page': 'analytics',
        'user_profile': user_profile,
        'user_name': user_profile.name if user_profile else request.user.username,
        'user_role': user_profile.role if user_profile else 'Unknown',
        'department': department,
        'batches': batches,
    }

    return render(request, 'students/academic_batch_list.html', context)


@login_required
def analytics_batch_semesters(request, department_id, batch_year):
    """
    View for showing all 8 semesters in a batch for analytics.
    URL: /analytics/department/<department_id>/batch/<batch_year>/
    """
    user_profile = UserProfile.get_by_email(request.user.email)
    
    if not user_profile or not user_profile.can_access_department_analytics():
        return render(request, 'students/access_denied.html', {
            'user_profile': user_profile,
            'user_name': user_profile.name if user_profile else request.user.username,
            'user_role': user_profile.role if user_profile else 'Unknown',
            'message': 'You do not have access to academic analytics.',
        })
    
    try:
        department = Department.objects.get(id=department_id, is_active=True)
    except Department.DoesNotExist:
        return render(request, 'students/access_denied.html', {
            'message': 'Department not found.',
        })
    
    # Check department access for HOD
    if user_profile.role == UserProfile.Role.HOD and str(user_profile.department_id) != str(department_id):
        return render(request, 'students/access_denied.html', {
            'message': 'You can only access your own department.',
        })
    
    # Get all global semesters and enrich with batch-specific status
    from students.models import Semester, ProgramSemester
    all_semesters = Semester.objects.all().order_by('number')
    
    # Get the program semester records for this batch to get status
    program_semester_map = {
        ps.semester_id: ps for ps in ProgramSemester.objects.filter(batch_year=batch_year)
    }
    
    # Enrich semesters with status
    semesters = []
    for semester in all_semesters:
        prog_sem = program_semester_map.get(semester.number)
        status = prog_sem.status if prog_sem else 'inactive'
        semesters.append({
            'semester': semester,
            'number': semester.number,
            'name': semester.name,
            'year': semester.year,
            'status': status,
        })
    
    context = {
        'active_page': 'analytics',
        'user_profile': user_profile,
        'user_name': user_profile.name if user_profile else request.user.username,
        'user_role': user_profile.role if user_profile else 'Unknown',
        'department': department,
        'batch_year': batch_year,
        'semesters': semesters,
    }
    
    return render(request, 'students/analytics_batch_semesters.html', context)


@login_required
@ensure_csrf_cookie
def analytics_semester_details(request, department_id, batch_year, semester_number):
    """
    View for semester analytics with internals and end-semester tabs.
    URL: /analytics/department/<department_id>/batch/<batch_year>/sem/<semester_number>/
    """
    user_profile = UserProfile.get_by_email(request.user.email)
    
    if not user_profile or not user_profile.can_access_department_analytics():
        return render(request, 'students/access_denied.html', {
            'user_profile': user_profile,
            'user_name': user_profile.name if user_profile else request.user.username,
            'user_role': user_profile.role if user_profile else 'Unknown',
            'message': 'You do not have access to academic analytics.',
        })
    
    from students.models import Semester
    try:
        department = Department.objects.get(id=department_id, is_active=True)
        semester = Semester.objects.get(number=semester_number)
        program_semester = ProgramSemester.objects.get(
            semester=semester,
            batch_year=batch_year
        )
    except (Department.DoesNotExist, Semester.DoesNotExist, ProgramSemester.DoesNotExist):
        return render(request, 'students/access_denied.html', {
            'message': 'Department or semester not found.',
        })
    
    # Check department access for HOD
    if user_profile.role == UserProfile.Role.HOD and str(user_profile.department_id) != str(department_id):
        return render(request, 'students/access_denied.html', {
            'message': 'You can only access your own department.',
        })
    
    # Get subjects for this semester and department
    subjects = Subject.objects.filter(semester=semester, department=department).order_by('code')
    
    # Get students in this batch and department
    students = Student.objects.filter(
        department_id=department_id,
        academic_year_joining=batch_year,
        is_active=True
    ).order_by('roll_number')
    
    # Get semester summary for SGPA and arrears
    semester_summaries = SemesterSummary.objects.filter(
        student__in=students,
        program_semester=program_semester
    ).select_related('student')
    
    # Create a dict for quick lookup
    summary_dict = {summary.student_id: summary for summary in semester_summaries}
    
    # Get selected filters from request
    selected_internal = request.GET.get('internal', '1')
    selected_subject_code = request.GET.get('subject', '')
    active_tab = request.GET.get('tab', 'internals')
    
    results_data = []
    
    if active_tab == 'internals' and selected_subject_code:
        try:
            subject = Subject.objects.get(code=selected_subject_code, semester=semester, department=department)
            subject_results = SubjectResult.objects.filter(
                student__in=students,
                subject=subject
            ).select_related('student')
            
            for result in subject_results:
                internal_field = f'internal{selected_internal}'
                mark = getattr(result, internal_field)
                results_data.append({
                    'result_id': str(result.id),
                    'student': result.student,
                    'mark': mark,
                    'internal1': result.internal1,
                    'internal2': result.internal2,
                    'internal3': result.internal3,
                    'end_sem_marks': result.end_sem_marks,
                    'grade': result.grade,
                    'grade_points': result.grade_points,
                    'summary': summary_dict.get(result.student_id),
                })
        except Subject.DoesNotExist:
            pass
    
    elif active_tab == 'end_semester' and selected_subject_code:
        try:
            subject = Subject.objects.get(code=selected_subject_code, semester=semester, department=department)
            # Load from the dedicated EndSemesterResult table
            end_sem_results = EndSemesterResult.objects.filter(
                student__in=students,
                subject=subject
            ).select_related('student')
            
            for result in end_sem_results:
                results_data.append({
                    'result_id': str(result.id),
                    'student': result.student,
                    'marks': result.marks,
                    'max_marks': result.max_marks,
                    'grade': result.grade,
                    'grade_points': result.grade_points,
                    'result_status': result.result_status,
                    'exam_date': result.exam_date,
                    'is_revaluation': result.is_revaluation,
                    'summary': summary_dict.get(result.student_id),
                })
        except Subject.DoesNotExist:
            pass
    
    context = {
        'active_page': 'analytics',
        'user_profile': user_profile,
        'user_name': user_profile.name if user_profile else request.user.username,
        'user_role': user_profile.role if user_profile else 'Unknown',
        'department': department,
        'batch_year': batch_year,
        'semester': semester,
        'program_semester': program_semester,
        'subjects': subjects,
        'students': students,
        'results_data': results_data,
        'selected_internal': selected_internal,
        'selected_subject_code': selected_subject_code,
        'active_tab': active_tab,
        'summary_dict': summary_dict,
    }
    
    return render(request, 'students/analytics_semester_details.html', context)


# ==================== SUBJECT MANAGEMENT API VIEWS ====================

@login_required
@require_http_methods(["POST"])
def subject_add(request, department_id, semester_number):
    """Add a new subject for a department and semester."""
    from students.models import Semester
    user_profile = UserProfile.get_by_email(request.user.email)
    if not user_profile or not user_profile.can_access_department_analytics():
        return JsonResponse({'success': False, 'error': 'Permission denied.'}, status=403)

    try:
        data = json.loads(request.body)
        code = data.get('code', '').strip().upper()
        name = data.get('name', '').strip()
        credits = int(data.get('credits', 3))

        if not code or not name:
            return JsonResponse({'success': False, 'error': 'Code and name are required.'}, status=400)
        if credits < 1 or credits > 10:
            return JsonResponse({'success': False, 'error': 'Credits must be between 1 and 10.'}, status=400)

        department = Department.objects.get(id=department_id, is_active=True)
        semester = Semester.objects.get(number=semester_number)

        if Subject.objects.filter(code=code, department=department, semester=semester).exists():
            return JsonResponse({'success': False, 'error': f'Subject with code "{code}" already exists in this semester.'}, status=400)

        subject = Subject.objects.create(
            code=code,
            name=name,
            department=department,
            semester=semester,
            credits=credits,
        )
        return JsonResponse({
            'success': True,
            'subject': {'code': subject.code, 'name': subject.name, 'credits': subject.credits}
        })
    except Department.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Department not found.'}, status=404)
    except Semester.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Semester not found.'}, status=404)
    except (ValueError, KeyError) as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=400)


@login_required
@require_http_methods(["POST"])
def subject_update(request, department_id, semester_number):
    """Update an existing subject's name and credits."""
    from students.models import Semester
    user_profile = UserProfile.get_by_email(request.user.email)
    if not user_profile or not user_profile.can_access_department_analytics():
        return JsonResponse({'success': False, 'error': 'Permission denied.'}, status=403)

    try:
        data = json.loads(request.body)
        code = data.get('code', '').strip().upper()
        name = data.get('name', '').strip()
        credits = int(data.get('credits', 3))

        if not code or not name:
            return JsonResponse({'success': False, 'error': 'Code and name are required.'}, status=400)
        if credits < 1 or credits > 10:
            return JsonResponse({'success': False, 'error': 'Credits must be between 1 and 10.'}, status=400)

        department = Department.objects.get(id=department_id, is_active=True)
        semester = Semester.objects.get(number=semester_number)
        subject = Subject.objects.get(code=code, department=department, semester=semester)

        subject.name = name
        subject.credits = credits
        subject.save()

        return JsonResponse({
            'success': True,
            'subject': {'code': subject.code, 'name': subject.name, 'credits': subject.credits}
        })
    except Subject.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Subject not found.'}, status=404)
    except (Department.DoesNotExist, Semester.DoesNotExist):
        return JsonResponse({'success': False, 'error': 'Department or semester not found.'}, status=404)
    except (ValueError, KeyError) as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=400)


@login_required
@require_http_methods(["POST"])
def subject_delete(request, department_id, semester_number):
    """Delete a subject and its associated results."""
    from students.models import Semester
    user_profile = UserProfile.get_by_email(request.user.email)
    if not user_profile or not user_profile.can_access_department_analytics():
        return JsonResponse({'success': False, 'error': 'Permission denied.'}, status=403)

    try:
        data = json.loads(request.body)
        code = data.get('code', '').strip().upper()

        if not code:
            return JsonResponse({'success': False, 'error': 'Subject code is required.'}, status=400)

        department = Department.objects.get(id=department_id, is_active=True)
        semester = Semester.objects.get(number=semester_number)
        subject = Subject.objects.get(code=code, department=department, semester=semester)
        subject.delete()

        return JsonResponse({'success': True, 'message': f'Subject "{code}" deleted successfully.'})
    except Subject.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Subject not found.'}, status=404)
    except (Department.DoesNotExist, Semester.DoesNotExist):
        return JsonResponse({'success': False, 'error': 'Department or semester not found.'}, status=404)
    except (ValueError, KeyError) as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=400)


# ─────────────────────────────────────────────────────────────────────────────
# Marks (SubjectResult) CRUD API
# ─────────────────────────────────────────────────────────────────────────────

MARKS_FIELDS = ('internal1', 'internal2', 'internal3', 'end_sem_marks', 'grade', 'grade_points')


def _marks_row_json(r):
    """Serialise a SubjectResult into a JSON-safe dict."""
    return {
        'id':            str(r.id),
        'roll_number':   r.student.roll_number,
        'reg_number':    str(r.student.registration_number or ''),
        'student_name':  r.student.student_name,
        'subject_code':  r.subject.code,
        'subject_name':  r.subject.name,
        'internal1':     str(r.internal1)      if r.internal1      is not None else '',
        'internal2':     str(r.internal2)      if r.internal2      is not None else '',
        'internal3':     str(r.internal3)      if r.internal3      is not None else '',
        'end_sem_marks': str(r.end_sem_marks)  if r.end_sem_marks  is not None else '',
        'grade':         r.grade               or '',
        'grade_points':  str(r.grade_points)   if r.grade_points   is not None else '',
    }


@login_required
@require_http_methods(["GET"])
def marks_list_api(request, department_id, batch_year, semester_number):
    """Return all SubjectResult rows for dept/batch/semester as JSON."""
    from students.models import Semester
    user_profile = UserProfile.get_by_email(request.user.email)
    if not user_profile or not user_profile.can_access_department_analytics():
        return JsonResponse({'error': 'Permission denied.'}, status=403)

    try:
        department = Department.objects.get(id=department_id, is_active=True)
        semester   = Semester.objects.get(number=semester_number)
    except Exception:
        return JsonResponse({'error': 'Department or semester not found.'}, status=404)

    students = Student.objects.filter(
        department_id=department.id, is_active=True
    ).values_list('id', flat=True)

    results = (
        SubjectResult.objects
        .filter(student_id__in=students, subject__semester=semester,
                subject__department=department)
        .select_related('student', 'subject')
        .order_by('student__roll_number', 'subject__code')
    )

    subject_filter = request.GET.get('subject')
    if subject_filter:
        results = results.filter(subject__code=subject_filter.upper())

    search = request.GET.get('q', '').strip()
    if search:
        results = results.filter(
            Q(student__roll_number__icontains=search) |
            Q(student__student_name__icontains=search) |
            Q(student__registration_number__icontains=search)
        )

    return JsonResponse({'results': [_marks_row_json(r) for r in results]})


@login_required
@require_http_methods(["POST"])
def marks_update_api(request, result_id):
    """Update one or more mark fields on a SubjectResult row."""
    from decimal import Decimal, InvalidOperation
    user_profile = UserProfile.get_by_email(request.user.email)
    if not user_profile or not user_profile.can_access_department_analytics():
        return JsonResponse({'error': 'Permission denied.'}, status=403)

    try:
        result = SubjectResult.objects.select_related('student', 'subject').get(id=result_id)
    except SubjectResult.DoesNotExist:
        return JsonResponse({'error': 'Record not found.'}, status=404)

    try:
        data = json.loads(request.body)
    except Exception:
        return JsonResponse({'error': 'Invalid JSON body.'}, status=400)

    changed = []
    for field in MARKS_FIELDS:
        if field not in data:
            continue
        raw = data[field]
        if field in ('internal1', 'internal2', 'internal3', 'end_sem_marks', 'grade_points'):
            if raw == '' or raw is None:
                setattr(result, field, None)
            else:
                try:
                    setattr(result, field, Decimal(str(raw)))
                except InvalidOperation:
                    return JsonResponse({'error': f'Invalid value for {field}: {raw!r}'}, status=400)
        elif field == 'grade':
            setattr(result, field, raw.strip().upper() if raw else None)
        changed.append(field)

    if not changed:
        return JsonResponse({'error': 'No valid fields provided.'}, status=400)

    result.save()
    return JsonResponse({'success': True, 'result': _marks_row_json(result)})


@login_required
@require_http_methods(["POST"])
def marks_delete_api(request, result_id):
    """Delete a SubjectResult row entirely."""
    user_profile = UserProfile.get_by_email(request.user.email)
    if not user_profile or not user_profile.can_access_department_analytics():
        return JsonResponse({'error': 'Permission denied.'}, status=403)

    try:
        result = SubjectResult.objects.get(id=result_id)
    except SubjectResult.DoesNotExist:
        return JsonResponse({'error': 'Record not found.'}, status=404)

    result.delete()
    return JsonResponse({'success': True})


# ==================== END SEMESTER RESULT API VIEWS ====================

END_SEM_FIELDS = ('marks', 'max_marks', 'grade', 'grade_points', 'result_status', 'is_revaluation')


def _end_sem_row_json(r):
    """Serialise an EndSemesterResult into a JSON-safe dict."""
    return {
        'id':             str(r.id),
        'roll_number':    r.student.roll_number,
        'reg_number':     str(r.student.registration_number or ''),
        'student_name':   r.student.student_name,
        'subject_code':   r.subject.code,
        'subject_name':   r.subject.name,
        'marks':          str(r.marks)         if r.marks         is not None else '',
        'max_marks':      str(r.max_marks)     if r.max_marks     is not None else '',
        'grade':          r.grade              or '',
        'grade_points':   str(r.grade_points)  if r.grade_points  is not None else '',
        'result_status':  r.result_status      or '',
        'exam_date':      str(r.exam_date)     if r.exam_date     else '',
        'is_revaluation': r.is_revaluation,
    }


@login_required
@require_http_methods(["GET"])
def end_sem_list_api(request, department_id, batch_year, semester_number):
    """Return all EndSemesterResult rows for dept/batch/semester as JSON."""
    from students.models import Semester
    user_profile = UserProfile.get_by_email(request.user.email)
    if not user_profile or not user_profile.can_access_department_analytics():
        return JsonResponse({'error': 'Permission denied.'}, status=403)

    # HOD restriction
    if user_profile.role == UserProfile.Role.HOD and str(user_profile.department_id) != str(department_id):
        return JsonResponse({'error': 'Access restricted to your department.'}, status=403)

    try:
        department = Department.objects.get(id=department_id, is_active=True)
        semester   = Semester.objects.get(number=semester_number)
    except Exception:
        return JsonResponse({'error': 'Department or semester not found.'}, status=404)

    students = Student.objects.filter(
        department_id=department.id,
        academic_year_joining=batch_year,
        is_active=True
    ).values_list('id', flat=True)

    results = (
        EndSemesterResult.objects
        .filter(student_id__in=students, subject__semester=semester,
                subject__department=department)
        .select_related('student', 'subject')
        .order_by('student__roll_number', 'subject__code')
    )

    subject_filter = request.GET.get('subject')
    if subject_filter:
        results = results.filter(subject__code=subject_filter.upper())

    search = request.GET.get('q', '').strip()
    if search:
        results = results.filter(
            Q(student__roll_number__icontains=search) |
            Q(student__student_name__icontains=search) |
            Q(student__registration_number__icontains=search)
        )

    return JsonResponse({'results': [_end_sem_row_json(r) for r in results]})


@login_required
@require_http_methods(["POST"])
def end_sem_update_api(request, result_id):
    """Update one or more fields on an EndSemesterResult row."""
    from decimal import Decimal, InvalidOperation
    user_profile = UserProfile.get_by_email(request.user.email)
    if not user_profile or not user_profile.can_access_department_analytics():
        return JsonResponse({'error': 'Permission denied.'}, status=403)

    try:
        result = EndSemesterResult.objects.select_related('student', 'subject').get(id=result_id)
    except EndSemesterResult.DoesNotExist:
        return JsonResponse({'error': 'Record not found.'}, status=404)

    try:
        data = json.loads(request.body)
    except Exception:
        return JsonResponse({'error': 'Invalid JSON body.'}, status=400)

    changed = []
    for field in END_SEM_FIELDS:
        if field not in data:
            continue
        raw = data[field]
        if field in ('marks', 'max_marks', 'grade_points'):
            if raw == '' or raw is None:
                setattr(result, field, None)
            else:
                try:
                    setattr(result, field, Decimal(str(raw)))
                except InvalidOperation:
                    return JsonResponse({'error': f'Invalid value for {field}: {raw!r}'}, status=400)
        elif field == 'grade':
            setattr(result, field, raw.strip().upper() if raw else None)
        elif field == 'result_status':
            setattr(result, field, raw.strip().upper() if raw else '')
        elif field == 'is_revaluation':
            setattr(result, field, bool(raw))
        changed.append(field)

    if not changed:
        return JsonResponse({'error': 'No valid fields provided.'}, status=400)

    result.save()
    return JsonResponse({'success': True, 'result': _end_sem_row_json(result)})


@login_required
@require_http_methods(["POST"])
def end_sem_delete_api(request, result_id):
    """Delete an EndSemesterResult row entirely."""
    user_profile = UserProfile.get_by_email(request.user.email)
    if not user_profile or not user_profile.can_access_department_analytics():
        return JsonResponse({'error': 'Permission denied.'}, status=403)

    try:
        result = EndSemesterResult.objects.get(id=result_id)
    except EndSemesterResult.DoesNotExist:
        return JsonResponse({'error': 'Record not found.'}, status=404)

    result.delete()
    return JsonResponse({'success': True})
