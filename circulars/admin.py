from django.contrib import admin
from .models import Circular


@admin.register(Circular)
class CircularAdmin(admin.ModelAdmin):
    list_display = ('title', 'user', 'category', 'created_at')
    list_filter = ('category', 'created_at')
    search_fields = ('title', 'content')
    readonly_fields = ('created_at',)
    ordering = ('-created_at',)
