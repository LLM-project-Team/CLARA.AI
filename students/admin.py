from django.contrib import admin
from .models import Student, Department


@admin.register(Department)
class DepartmentAdmin(admin.ModelAdmin):
    """Read-only view of departments from cloud DB"""
    list_display = ('name', 'full_name', 'is_active', 'created_at')
    list_filter = ('is_active',)
    search_fields = ('name', 'full_name')
    readonly_fields = ('id', 'institution_id', 'name', 'full_name', 'is_active', 'created_at')
    
    def has_add_permission(self, request):
        return False
    
    def has_delete_permission(self, request, obj=None):
        return False
    
    def has_change_permission(self, request, obj=None):
        return False


@admin.register(Student)
class StudentAdmin(admin.ModelAdmin):
    """Read-only view of students from cloud DB"""
    list_display = ('roll_number', 'student_name', 'department_id', 'batch_year', 'gender')
    list_filter = ('gender', 'course_type', 'batch_year', 'hosteller')
    search_fields = ('student_name', 'roll_number', 'register_number', 'college_email')
    readonly_fields = ('id', 'institution_id', 'department_id', 'salutation', 'student_name', 
                       'college_email', 'register_number', 'roll_number', 'gender', 'blood_group',
                       'mobile_number', 'district', 'date_of_birth', 'date_of_admission',
                       'academic_year_join', 'course_type', 'admission_quota', 'hosteller',
                       'is_hosteller', 'batch_year', 'father_name', 'father_occupation',
                       'mother_name', 'mother_occupation', 'religion', 'community', 'caste',
                       'aadhaar_number', 'permanent_address', 'first_graduate', 'created_at')
    ordering = ('roll_number',)
    
    def has_add_permission(self, request):
        return False
    
    def has_delete_permission(self, request, obj=None):
        return False
    
    def has_change_permission(self, request, obj=None):
        return False
