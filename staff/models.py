from django.db import models
import uuid


class Staff(models.Model):
    """
    Model to read from the existing 'staff' table in the database.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    institution_id = models.UUIDField(null=True, blank=True)
    department_id = models.UUIDField(null=True, blank=True)
    salutation = models.CharField(max_length=20, null=True, blank=True)
    name = models.CharField(max_length=200)
    staff_code = models.CharField(max_length=50, null=True, blank=True)
    designation = models.CharField(max_length=100, null=True, blank=True)
    qualification = models.CharField(max_length=200, null=True, blank=True)
    official_email = models.CharField(max_length=200, null=True, blank=True)
    date_of_join = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'staff'  # Maps to existing 'staff' table
        managed = False     # Django won't create/alter this table
        ordering = ['name']

    def __str__(self):
        return f"{self.staff_code} - {self.name}"
