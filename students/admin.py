from django.contrib import admin
from .models import Student, Department


@admin.register(Department)
class DepartmentAdmin(admin.ModelAdmin):
    """Read-only view of departments from cloud DB"""
    list_display = ('name', 'full_name', 'is_active', 'created_at')
    list_filter = ('is_active',)
    search_fields = ('name', 'full_name')
    readonly_fields = ('id', 'name', 'full_name', 'is_active', 'created_at', 'college_code')
    
    def has_add_permission(self, request):
        return False
    
    def has_delete_permission(self, request, obj=None):
        return False
    
    def has_change_permission(self, request, obj=None):
        return False


@admin.register(Student)
class StudentAdmin(admin.ModelAdmin):
    """Read-only view of students from cloud DB"""
    list_display = ('roll_number', 'student_name', 'department_id', 'academic_year_joining', 'gender')
    list_filter = ('gender', 'hosteller')
    search_fields = ('student_name', 'roll_number', 'registration_number', 'email_id')
    readonly_fields = ('id', 'college_code', 'department_id', 'student_name', 
                       'email_id', 'registration_number', 'roll_number', 'gender', 'blood_group',
                       'mobile_number', 'district', 'date_of_birth', 'date_of_admission',
                       'academic_year_joining', 'mq_gq', 'hosteller',
                       'father_name',
                       'mother_name', 'religion', 'community', 'caste',
                       'aadhaar_number', 'permanent_address', 'is_first_graduate', 'created_at',
                       'is_active', 'branch_specialization', 'has_special_admission_quota',
                       'is_differently_abled')
    ordering = ('roll_number',)
    
    def has_add_permission(self, request):
        return False
    
    def has_delete_permission(self, request, obj=None):
        return False
    
    def has_change_permission(self, request, obj=None):
        return False
