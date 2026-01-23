from django.db import models
from django.contrib.auth import get_user_model

User = get_user_model()

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