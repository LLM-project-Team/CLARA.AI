from django.contrib.auth.base_user import BaseUserManager
from django.contrib.auth.models import AbstractUser
from django.db import models

# Create your models here.
"""
1 .The CustomUser model defines how the user table should look.
AbstractUser / AbstractBaseUser provide Django’s default user behavior.
Migrations turn this definition into the real database table.
Changing the model alone is not enough, because authentication also depends on how users are created.

2 .BaseUserManager customizes how users are created.
   In create_user, Django:

      normalizes the email

      creates a user object in RAM using self.model                                                                                                                                                                                                                                                     

      does not pass the password yet because passwords must be hashed and hashing requires a user instance

      hashes the password using set_password

      saves the user to the database

3 .save() is the only step that actually writes to the database.

4 .create_superuser is a function, not a class, because a superuser is not a different type of user.
It only adds permission flags and then reuses create_user.

5 .When createsuperuser is run in the terminal, Django’s management command collects the email and password first, then calls create_superuser(email, password) with those values.
"""


class CustomUserManager(BaseUserManager):               #used mostly by the developers(terminal) or non-website parts(like terminal) or no form needed part(but this is not highly recommended to remember) this is to create a user in the DB  ,remember save() always save things to the DB ,so if you see save() realize it is going to DB
    def create_user(self,email,password,**extra_fields):
        if not email:
            raise ValueError("Please Enter a Proper Email")

        email=self.normalize_email(email)
        user = self.model(email=email,**extra_fields)
        user.set_password(password)
        user.save()
        return user

    def create_superuser(self,email,password,**extra_fields):
        extra_fields.setdefault('is_staff',True)
        extra_fields.setdefault('is_superuser',True)
        extra_fields.setdefault('is_active',True)

        return self.create_user(email,password,**extra_fields)


class CustomUser(AbstractUser):
    email = models.EmailField(unique=True)
    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['username']          #this line is only for superuser

    objects = CustomUserManager()


import uuid

class UserProfile(models.Model):
    """
    Model to read from the existing 'users' table in the database.
    This table contains role information (ADMIN, PRINCIPAL, DEAN, HOD).
    
    Role Permissions:
    ==================
    ADMIN:
        - Can add new users (like HODs) and manage all existing users
        - Can change passwords, emails, usernames of all users
        - Can ALTER/EDIT/MANAGE Staff DB (full CRUD access)
        - CANNOT use Circular Generator or AI features
        
    PRINCIPAL:
        - CAN use Circular Generator and AI features
        - Can VIEW ONLY Staff DB (read-only, no edit)
        - Can manage Students DB (add/edit students)
        - Access to ALL academic analytics (sorted by department)
        
    DEAN:
        - CAN use Circular Generator and AI features
        - Can VIEW ONLY Staff DB (read-only, no edit)
        - Can manage Students DB (add/edit students)
        - Access to ALL academic analytics (sorted by batch)
        
    HOD:
        - CANNOT view Staff DB (restricted)
        - Can manage Students DB of their department (add/edit students)
        - Access to department academic analytics only
    """
    class Role(models.TextChoices):
        ADMIN = 'ADMIN', 'Administrator'
        PRINCIPAL = 'PRINCIPAL', 'Principal'
        DEAN = 'DEAN', 'Dean'
        HOD = 'HOD', 'HOD'
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    institution_id = models.UUIDField(null=True, blank=True)
    department_id = models.UUIDField(null=True, blank=True)
    name = models.CharField(max_length=100)
    email = models.CharField(max_length=120, unique=True)
    password_hash = models.CharField(max_length=255)
    role = models.CharField(max_length=20, choices=Role.choices)
    is_active = models.BooleanField(default=True)
    last_login = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'users'  # Maps to existing 'users' table
        managed = False     # Django won't create/alter this table

    def __str__(self):
        return f"{self.name} ({self.role})"
    
    @classmethod
    def get_by_email(cls, email):
        """Get user profile by email"""
        try:
            return cls.objects.get(email=email)
        except cls.DoesNotExist:
            return None
    
    # ==================== ADMIN PERMISSIONS ====================
    def is_admin(self):
        """Check if user is Admin"""
        return self.role == self.Role.ADMIN
    
    def can_manage_all_users(self):
        """Admin can add new users, manage existing users, change passwords/emails"""
        return self.role == self.Role.ADMIN
    
    def can_add_users(self):
        """Only Admin can add new users (like HODs)"""
        return self.role == self.Role.ADMIN
    
    # ==================== CIRCULAR & AI FEATURES PERMISSIONS ====================
    def can_generate_circular(self):
        """Only Principal and Dean can generate circulars - NOT Admin"""
        return self.role in [self.Role.PRINCIPAL, self.Role.DEAN]
    
    def can_use_ai_features(self):
        """Only Principal and Dean can use AI features - NOT Admin"""
        return self.role in [self.Role.PRINCIPAL, self.Role.DEAN]
    
    # ==================== STAFF DB PERMISSIONS ====================
    def can_view_staff(self):
        """Admin, Principal, Dean can view all staff. HOD can view staff in their department."""
        return self.role in [self.Role.ADMIN, self.Role.PRINCIPAL, self.Role.DEAN, self.Role.HOD]
    
    def can_modify_staff_db(self):
        """ONLY Admin can add/edit/delete staff. Principal & Dean are view-only."""
        return self.role == self.Role.ADMIN
    
    def can_add_staff(self):
        """Only Admin can add new staff"""
        return self.role == self.Role.ADMIN
    
    def can_edit_staff(self):
        """Only Admin can edit staff details"""
        return self.role == self.Role.ADMIN
    
    def can_delete_staff(self):
        """Only Admin can delete staff"""
        return self.role == self.Role.ADMIN
    
    def can_manage_staff(self):
        """All roles can manage/view staff (with appropriate restrictions)"""
        return self.role in [self.Role.ADMIN, self.Role.PRINCIPAL, self.Role.DEAN, self.Role.HOD]
    
    # ==================== STUDENTS DB PERMISSIONS ====================
    def can_view_students(self):
        """All roles can view students (HOD limited to their department)"""
        return self.role in [self.Role.ADMIN, self.Role.PRINCIPAL, self.Role.DEAN, self.Role.HOD]
    
    def can_add_students(self):
        """All users can add new students (HOD: their department only)"""
        return self.role in [self.Role.ADMIN, self.Role.PRINCIPAL, self.Role.DEAN, self.Role.HOD]
    
    def can_edit_students(self):
        """All users can edit student details (HOD: their department only)"""
        return self.role in [self.Role.ADMIN, self.Role.PRINCIPAL, self.Role.DEAN, self.Role.HOD]
    
    def can_delete_students(self):
        """Principal, Dean, Admin can delete students. HOD cannot delete."""
        return self.role in [self.Role.ADMIN, self.Role.PRINCIPAL, self.Role.DEAN]
    
    def can_manage_students(self):
        """All roles can manage students (add/edit)"""
        return self.role in [self.Role.ADMIN, self.Role.PRINCIPAL, self.Role.DEAN, self.Role.HOD]
    
    # ==================== ACADEMIC ANALYTICS PERMISSIONS ====================
    def can_access_all_analytics(self):
        """Principal and Dean can access entire students academic analytics"""
        return self.role in [self.Role.PRINCIPAL, self.Role.DEAN]
    
    def can_access_department_analytics(self):
        """HOD can access academic analytics of their department only"""
        return self.role in [self.Role.PRINCIPAL, self.Role.DEAN, self.Role.HOD]
    
    def get_analytics_scope(self):
        """
        Returns the scope of academic analytics the user can access.
        - PRINCIPAL/DEAN: 'all' - Can view all departments and batches
        - HOD: 'department' - Can only view their department's analytics
        - ADMIN: None - Admin manages users, not analytics
        """
        if self.role in [self.Role.PRINCIPAL, self.Role.DEAN]:
            return 'all'
        elif self.role == self.Role.HOD:
            return 'department'
        return None
    
    def get_analytics_order_preference(self):
        """
        Returns how analytics should be ordered/sorted for each role.
        - PRINCIPAL: By department (overall institutional view)
        - DEAN: By batch (academic year focus)
        - HOD: By batch within their department
        """
        if self.role == self.Role.PRINCIPAL:
            return 'department'
        elif self.role == self.Role.DEAN:
            return 'batch'
        elif self.role == self.Role.HOD:
            return 'batch'  # Within their department
        return None
    
    # ==================== GENERAL PERMISSIONS ====================
    def can_access_all_features(self):
        """Principal and Dean have access to all features (circular, AI, analytics)"""
        return self.role in [self.Role.PRINCIPAL, self.Role.DEAN]
    
    def can_access_admin_panel(self):
        """Only Admin can access Django admin panel for user management"""
        return self.role == self.Role.ADMIN
    
    def can_access_website_data(self):
        """Admin can manage data within website (users, staff)"""
        return self.role == self.Role.ADMIN
    
    def get_accessible_departments(self):
        """
        Returns department IDs the user can access.
        - ADMIN/PRINCIPAL/DEAN: All departments (returns None to indicate all)
        - HOD: Only their department_id
        """
        if self.role in [self.Role.ADMIN, self.Role.PRINCIPAL, self.Role.DEAN]:
            return None  # None means all departments
        elif self.role == self.Role.HOD:
            return [self.department_id] if self.department_id else []
        return []
    
    def get_dashboard_features(self):
        """
        Returns list of features available on dashboard for each role.
        """
        features = []
        
        if self.role == self.Role.ADMIN:
            features = ['user_management', 'staff_management']
        elif self.role == self.Role.PRINCIPAL:
            features = ['circular_generator', 'ai_features', 'student_management', 
                       'staff_view', 'analytics_all']
        elif self.role == self.Role.DEAN:
            features = ['circular_generator', 'ai_features', 'student_management', 
                       'staff_view', 'analytics_all']
        elif self.role == self.Role.HOD:
            features = ['student_management', 'analytics_department']
        
        return features
