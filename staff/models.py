from django.db import models
import uuid


class Staff(models.Model):
    """
    Model to read from the existing 'staff' table in the database.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    institution_id = models.UUIDField(null=True, blank=True)
    department_id = models.UUIDField(null=True, blank=True)
    user_id = models.UUIDField(null=True, blank=True)
    name = models.CharField(max_length=200)
    designation = models.CharField(max_length=100, null=True, blank=True)
    employee_code = models.CharField(max_length=50, null=True, blank=True)
    mobile_number = models.CharField(max_length=20, null=True, blank=True)
    email = models.CharField(max_length=200, null=True, blank=True)
    date_of_joining = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    highest_qualification = models.CharField(max_length=200, null=True, blank=True)
    area_of_specialization = models.CharField(max_length=200, null=True, blank=True)
    is_currently_associated = models.BooleanField(default=True)
    full_or_part_time = models.CharField(max_length=20, null=True, blank=True)
    date_of_leaving = models.DateField(null=True, blank=True)

    class Meta:
        db_table = 'staff'  # Maps to existing 'staff' table
        managed = False     # Django won't create/alter this table
        ordering = ['name']

    def __str__(self):
        return f"{self.employee_code} - {self.name}"

    # Backward-compatible properties for views/templates that use old field names
    @property
    def staff_code(self):
        return self.employee_code

    @property
    def qualification(self):
        return self.highest_qualification

    @property
    def official_email(self):
        return self.email

    @property
    def date_of_join(self):
        return self.date_of_joining

    @property
    def is_active(self):
        return self.is_currently_associated
