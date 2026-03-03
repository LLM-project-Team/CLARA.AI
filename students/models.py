from django.db import models
from decimal import Decimal
import uuid


class Department(models.Model):
    """
    Model to read from the existing 'departments' table in the database.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    name = models.CharField(max_length=50)  # Short name like CSE, AIDS
    full_name = models.CharField(max_length=200)  # Full name
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    college_code = models.CharField(max_length=50, null=True, blank=True)

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
    college_code = models.CharField(max_length=50, null=True, blank=True)
    department_id = models.UUIDField(null=True, blank=True)
    student_name = models.CharField(max_length=200)
    date_of_birth = models.DateField(null=True, blank=True)
    gender = models.CharField(max_length=10, choices=GENDER_CHOICES)
    blood_group = models.CharField(max_length=10, null=True, blank=True)
    religion = models.CharField(max_length=50, null=True, blank=True)
    community = models.CharField(max_length=50, null=True, blank=True)
    caste = models.CharField(max_length=100, null=True, blank=True)
    aadhaar_number = models.CharField(max_length=20, null=True, blank=True)
    is_first_graduate = models.BooleanField(default=False, null=True, blank=True)
    has_special_admission_quota = models.BooleanField(default=False, null=True, blank=True)
    is_differently_abled = models.BooleanField(default=False, null=True, blank=True)
    mobile_number = models.CharField(max_length=15, null=True, blank=True)
    email_id = models.CharField(max_length=200, null=True, blank=True)
    district = models.CharField(max_length=100, null=True, blank=True)
    permanent_address = models.TextField(null=True, blank=True)
    father_name = models.CharField(max_length=200, null=True, blank=True)
    mother_name = models.CharField(max_length=200, null=True, blank=True)
    academic_year_joining = models.CharField(max_length=10, null=True, blank=True)
    branch_specialization = models.CharField(max_length=200, null=True, blank=True)
    date_of_admission = models.DateField(null=True, blank=True)
    mq_gq = models.CharField(max_length=50, null=True, blank=True)
    registration_number = models.CharField(max_length=50, null=True, blank=True)
    hosteller = models.BooleanField(default=False)
    roll_number = models.CharField(max_length=20)
    created_at = models.DateTimeField(auto_now_add=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = 'students'  # Maps to existing 'students' table
        managed = False        # Django won't create/alter this table
        ordering = ['roll_number']

    def __str__(self):
        return f"{self.roll_number} - {self.student_name}"


class Semester(models.Model):
    """
    Global Semester model - Common across all departments (1-8 semesters).
    Represents semesters in a 4-year program (2 semesters per year).
    """
    number = models.IntegerField(unique=True, primary_key=True)  # 1..8
    name = models.CharField(max_length=20)  # "Sem 1", "Sem 2", etc.
    year = models.IntegerField()  # 1 (Sem 1-2), 2 (Sem 3-4), 3 (Sem 5-6), 4 (Sem 7-8)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'semesters'
        ordering = ['number']

    def __str__(self):
        return f"{self.name}"


class ProgramSemester(models.Model):
    """
    Model for program semesters per batch.
    Links batches with global semesters and tracks status per batch.
    """
    STATUS_CHOICES = [
        ('upcoming', 'Upcoming'),
        ('active', 'Active'),
        ('completed', 'Completed'),
        ('past', 'Past'),           # legacy alias for completed
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    semester = models.ForeignKey(Semester, on_delete=models.CASCADE, null=True, blank=True)
    batch_year = models.CharField(max_length=10)  # "2023", "2024", "2024-28", etc.
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='active')
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'program_semesters'
        unique_together = ('semester', 'batch_year')
        ordering = ['batch_year', 'semester__number']

    def __str__(self):
        return f"Batch {self.batch_year} - {self.semester}"


class Subject(models.Model):
    """
    Model for subjects in a semester (global).
    """
    code = models.CharField(max_length=20, primary_key=True)
    name = models.CharField(max_length=200)
    department = models.ForeignKey(Department, on_delete=models.CASCADE)
    semester = models.ForeignKey(Semester, on_delete=models.CASCADE, null=True, blank=True)
    credits = models.IntegerField(default=3)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'subjects'
        unique_together = ('department', 'semester', 'code')
        ordering = ['code']

    def __str__(self):
        return f"{self.code} - {self.name}"


class SubjectResult(models.Model):
    """
    Model for student results per subject.
    """
    GRADE_CHOICES = [
        ('O', 'Outstanding'),
        ('A+', 'Excellent'),
        ('A', 'Very Good'),
        ('B+', 'Good'),
        ('B', 'Above Average'),
        ('C', 'Average'),
        ('U', 'Fail'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    student = models.ForeignKey(Student, on_delete=models.CASCADE)
    subject = models.ForeignKey(Subject, on_delete=models.CASCADE)
    
    # Internal marks
    internal1 = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    internal2 = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    internal3 = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    
    # End semester marks and grade
    end_sem_marks = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    grade = models.CharField(max_length=2, choices=GRADE_CHOICES, null=True, blank=True)
    grade_points = models.DecimalField(max_digits=4, decimal_places=2, null=True, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'subject_results'
        unique_together = ('student', 'subject')
        ordering = ['student__roll_number']

    def __str__(self):
        return f"{self.student.roll_number} - {self.subject.code} - {self.grade or 'No Grade'}"


class SemesterSummary(models.Model):
    """
    Model for semester-wise summary (SGPA, arrears) per student.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    student = models.ForeignKey(Student, on_delete=models.CASCADE)
    program_semester = models.ForeignKey(ProgramSemester, on_delete=models.CASCADE)
    sgpa = models.DecimalField(max_digits=4, decimal_places=2, null=True, blank=True)
    total_credits = models.IntegerField(default=0)
    earned_credits = models.IntegerField(default=0)
    arrear_count = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'semester_summaries'
        unique_together = ('student', 'program_semester')
        ordering = ['student__roll_number']

    def __str__(self):
        return f"{self.student.roll_number} - {self.program_semester} - SGPA: {self.sgpa}"

# =====================================
# PDF ANALYSIS & RAG MODELS
# =====================================

class AnalyzedDocument(models.Model):
    """
    Model for storing metadata about uploaded and analyzed PDF documents
    Stores document info but not the actual PDF file (analysis results stored separately)
    """
    DOCUMENT_TYPE_CHOICES = [
        ('internal_marks', 'Internal Test Marks'),
        ('end_semester', 'End Semester Results'),
        ('attendance', 'Attendance Report'),
        ('other', 'Other Document'),
    ]
    
    STATUS_CHOICES = [
        ('uploaded', 'Uploaded'),
        ('processing', 'Processing'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    document_uuid = models.CharField(max_length=50, unique=True)  # Reference to extracted JSON
    department = models.ForeignKey(Department, on_delete=models.CASCADE)
    program_semester = models.ForeignKey(ProgramSemester, on_delete=models.CASCADE)
    
    document_type = models.CharField(max_length=20, choices=DOCUMENT_TYPE_CHOICES)
    original_filename = models.CharField(max_length=255)
    
    # Document metadata
    upload_date = models.DateTimeField(auto_now_add=True)
    processed_date = models.DateTimeField(null=True, blank=True)
    file_size = models.IntegerField(null=True, blank=True)  # in bytes
    total_pages = models.IntegerField(default=0)
    
    # Status tracking
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='uploaded')
    error_message = models.TextField(null=True, blank=True)
    
    # RAG indexing
    is_indexed = models.BooleanField(default=False)
    rag_collection_name = models.CharField(max_length=100, null=True, blank=True)
    
    # Extraction metadata
    total_records_extracted = models.IntegerField(default=0)
    total_students_processed = models.IntegerField(default=0)
    total_subjects_processed = models.IntegerField(default=0)
    
    uploaded_by = models.CharField(max_length=200, null=True, blank=True)  # User who uploaded
    
    class Meta:
        db_table = 'analyzed_documents'
        ordering = ['-upload_date']
        indexes = [
            models.Index(fields=['department', 'program_semester']),
            models.Index(fields=['status']),
            models.Index(fields=['is_indexed']),
        ]
    
    def __str__(self):
        return f"{self.original_filename} - {self.document_type} - {self.status}"


class DocumentAnalysisResult(models.Model):
    """
    Model for storing extracted academic data from analyzed documents
    Instead of storing the PDF, we store the extracted structured data
    """
    RESULT_TYPE_CHOICES = [
        ('marks', 'Marks/Grades'),
        ('attendance', 'Attendance'),
        ('other', 'Other Data'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    document = models.ForeignKey(AnalyzedDocument, on_delete=models.CASCADE, related_name='analysis_results')
    
    # Extracted data references
    student = models.ForeignKey(Student, on_delete=models.CASCADE, null=True, blank=True)
    subject = models.ForeignKey(Subject, on_delete=models.CASCADE, null=True, blank=True)
    
    # Result type and values
    result_type = models.CharField(max_length=20, choices=RESULT_TYPE_CHOICES)
    
    # Extracted marks (flexible storage)
    internal1 = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    internal2 = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    internal3 = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    end_sem_marks = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    grade = models.CharField(max_length=2, null=True, blank=True)
    
    # Confidence score (how confident the extraction was)
    confidence_score = models.DecimalField(max_digits=3, decimal_places=2, default=Decimal('0.00'))
    
    # Extracted raw data (JSON for flexibility)
    raw_extracted_data = models.JSONField(default=dict, blank=True)
    
    # Extraction context
    page_number = models.IntegerField(null=True, blank=True)
    source_text = models.TextField(null=True, blank=True)  # Original text from PDF
    
    # Status and validation
    is_verified = models.BooleanField(default=False)
    verification_notes = models.TextField(null=True, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'document_analysis_results'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['document', 'student']),
            models.Index(fields=['result_type']),
            models.Index(fields=['is_verified']),
        ]
    
    def __str__(self):
        return f"{self.document.original_filename} - {self.result_type}"


class EndSemesterResult(models.Model):
    """
    Separate model for end semester exam results.
    Stored independently from internal marks (SubjectResult) so they don't interfere.
    End semester results have their own grading, grade points, and SGPA calculations.
    """
    GRADE_CHOICES = [
        ('O', 'Outstanding'),
        ('A+', 'Excellent'),
        ('A', 'Very Good'),
        ('B+', 'Good'),
        ('B', 'Above Average'),
        ('C', 'Average'),
        ('U', 'Fail'),
        ('AB', 'Absent'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name='end_semester_results')
    subject = models.ForeignKey(Subject, on_delete=models.CASCADE, related_name='end_semester_results')
    
    # End semester marks
    marks = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    max_marks = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('100.00'))
    
    # Grade
    grade = models.CharField(max_length=2, choices=GRADE_CHOICES, null=True, blank=True)
    grade_points = models.DecimalField(max_digits=4, decimal_places=2, null=True, blank=True)
    
    # Result status
    result_status = models.CharField(max_length=10, default='PASS',
                                     choices=[('PASS', 'Pass'), ('FAIL', 'Fail'), ('AB', 'Absent'), ('WH', 'Withheld')])
    
    # Metadata
    exam_date = models.DateField(null=True, blank=True)
    is_revaluation = models.BooleanField(default=False)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'end_semester_results'
        unique_together = ('student', 'subject')
        ordering = ['student__roll_number', 'subject__code']
        indexes = [
            models.Index(fields=['student', 'subject']),
            models.Index(fields=['grade']),
            models.Index(fields=['result_status']),
        ]

    def __str__(self):
        return f"{self.student.roll_number} - {self.subject.code} - {self.grade or 'No Grade'}"


class RAGIndexMetadata(models.Model):
    """
    Model for tracking Chroma RAG index metadata
    Links Chroma collections to their source documents
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    document = models.OneToOneField(AnalyzedDocument, on_delete=models.CASCADE, related_name='rag_metadata')
    
    # Chroma collection info
    collection_name = models.CharField(max_length=100, unique=True)
    batch_id = models.CharField(max_length=50)
    semester_id = models.CharField(max_length=50)
    
    # Indexing status
    text_chunks_indexed = models.IntegerField(default=0)
    images_indexed = models.IntegerField(default=0)
    is_complete = models.BooleanField(default=False)
    
    # Timestamps
    index_created_at = models.DateTimeField(auto_now_add=True)
    last_query_at = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        db_table = 'rag_index_metadata'
        ordering = ['-index_created_at']
    
    def __str__(self):
        return f"RAG Index: {self.collection_name}"