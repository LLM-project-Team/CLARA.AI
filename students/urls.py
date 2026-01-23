from django.urls import path
from . import views

app_name = 'students'

urlpatterns = [
    # Entry point: List of departments
    path('', views.department_list, name='department_list'),
    
    # Academic Analytics
    path('analytics/', views.academic_analytics, name='academic_analytics'),
    path('analytics/<uuid:department_id>/', views.department_analytics, name='department_analytics'),
    
    # Add new student
    path('add/', views.student_add, name='student_add'),
    path('add/<uuid:department_id>/', views.student_add, name='student_add_dept'),
    path('add/<uuid:department_id>/<str:batch_year>/', views.student_add, name='student_add_batch'),
    
    # Batches for a department
    path('<uuid:department_id>/', views.batch_list, name='batch_list'),
    
    # Students for a department and batch
    path('<uuid:department_id>/<str:batch_year>/', views.student_list, name='student_list'),
    
    # Individual student detail and edit
    path('detail/<uuid:student_id>/', views.student_detail, name='student_detail'),
    path('edit/<uuid:student_id>/', views.student_edit, name='student_edit'),
]
