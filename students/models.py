from django.db import models
import uuid


class Department(models.Model):
    """
    Model to read from the existing 'departments' table in the database.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    institution_id = models.UUIDField(null=True, blank=True)
    name = models.CharField(max_length=50)  # Short name like CSE, AIDS
    full_name = models.CharField(max_length=200)  # Full name
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'departments'
        managed = False
        ordering = ['name']

    def __str__(self):
        return f"{self.name} - {self.full_name}"


class Student(models.Model):
    """
    Model to read from the existing 'students' table in the database.
    """
    GENDER_CHOICES = [
        ('MALE', 'Male'),
        ('FEMALE', 'Female'),
        ('OTHER', 'Other'),
    ]
    
    COURSE_TYPE_CHOICES = [
        ('UG', 'Undergraduate'),
        ('PG', 'Postgraduate'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    institution_id = models.UUIDField(null=True, blank=True)
    department_id = models.UUIDField(null=True, blank=True)
    salutation = models.CharField(max_length=10, null=True, blank=True)
    student_name = models.CharField(max_length=200)
    college_email = models.CharField(max_length=200, null=True, blank=True)
    register_number = models.CharField(max_length=50)
    roll_number = models.CharField(max_length=20)
    gender = models.CharField(max_length=10, choices=GENDER_CHOICES)
    blood_group = models.CharField(max_length=10, null=True, blank=True)
    mobile_number = models.CharField(max_length=15, null=True, blank=True)
    district = models.CharField(max_length=100, null=True, blank=True)
    date_of_birth = models.DateField(null=True, blank=True)
    date_of_admission = models.DateField(null=True, blank=True)
    academic_year_join = models.CharField(max_length=10, null=True, blank=True)
    course_type = models.CharField(max_length=5, choices=COURSE_TYPE_CHOICES, null=True, blank=True)
    admission_quota = models.CharField(max_length=50, null=True, blank=True)  # Admission Quota (MQ/GQ)
    hosteller = models.BooleanField(default=False)
    is_hosteller = models.BooleanField(default=False)
    batch_year = models.CharField(max_length=20, null=True, blank=True)
    
    # Parent/Guardian Information
    father_name = models.CharField(max_length=200, null=True, blank=True)
    father_occupation = models.CharField(max_length=100, null=True, blank=True)
    mother_name = models.CharField(max_length=200, null=True, blank=True)
    mother_occupation = models.CharField(max_length=100, null=True, blank=True)
    
    # Additional Personal Details
    religion = models.CharField(max_length=50, null=True, blank=True)
    community = models.CharField(max_length=50, null=True, blank=True)
    caste = models.CharField(max_length=100, null=True, blank=True)
    aadhaar_number = models.CharField(max_length=20, null=True, blank=True)
    permanent_address = models.TextField(null=True, blank=True)
    first_graduate = models.BooleanField(default=False, null=True, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'students'  # Maps to existing 'students' table
        managed = False        # Django won't create/alter this table
        ordering = ['roll_number']

    def __str__(self):
        return f"{self.roll_number} - {self.student_name}"
