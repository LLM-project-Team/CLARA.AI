from django.db import models
from django.contrib.auth import get_user_model

User = get_user_model()


class CircularTemplate(models.Model):
    """
    Stores the uploaded circular letterhead template (with college logo, header, signature).
    Only one active template per user at a time. The circular content is overlaid on this template.
    """
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='circular_templates')
    name = models.CharField(max_length=200, default='Default Template')
    template_image = models.ImageField(upload_to='circular_templates/')
    is_active = models.BooleanField(default=True)
    # Content area margins (in mm from top/bottom of the A4 page)
    content_top_margin = models.IntegerField(
        default=72,
        help_text='Top margin in mm where content area starts (below header/logo area)'
    )
    content_bottom_margin = models.IntegerField(
        default=45,
        help_text='Bottom margin in mm where content area ends (above signature area)'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at']

    def __str__(self):
        return f"{self.name} ({'Active' if self.is_active else 'Inactive'})"

    def save(self, *args, **kwargs):
        # Ensure only one active template per user
        if self.is_active:
            CircularTemplate.objects.filter(user=self.user, is_active=True).exclude(pk=self.pk).update(is_active=False)
        super().save(*args, **kwargs)

    @classmethod
    def get_active_template(cls, user):
        """Get the currently active template for a user"""
        return cls.objects.filter(user=user, is_active=True).first()


class Circular(models.Model):
    CATEGORY_CHOICES = [
        ('holiday', 'Holiday (Auto)'),
        ('manual', 'Manual Draft'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE)
    title = models.CharField(max_length=200)  # e.g., "Republic Day Notice"
    content = models.TextField()              # The generated text
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES, default='manual')
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.title