from django.contrib import admin
from .models import Circular, CircularTemplate


@admin.register(Circular)
class CircularAdmin(admin.ModelAdmin):
    list_display = ('title', 'user', 'category', 'created_at')
    list_filter = ('category', 'created_at')
    search_fields = ('title', 'content')
    readonly_fields = ('created_at',)
    ordering = ('-created_at',)


@admin.register(CircularTemplate)
class CircularTemplateAdmin(admin.ModelAdmin):
    list_display = ('name', 'user', 'is_active', 'content_top_margin', 'content_bottom_margin', 'updated_at')
    list_filter = ('is_active', 'created_at')
    search_fields = ('name', 'user__email')
    readonly_fields = ('created_at', 'updated_at')
    ordering = ('-updated_at',)
