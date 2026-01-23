from django.urls import path
from . import views

app_name = 'staff'

urlpatterns = [
    # Entry point: List of departments
    path('', views.department_list, name='department_list'),
    
    # Add new staff
    path('add/', views.staff_add, name='staff_add'),
    path('add/<uuid:department_id>/', views.staff_add, name='staff_add_dept'),
    
    # Staff list for a department
    path('<uuid:department_id>/', views.staff_list, name='staff_list'),
    
    # Individual staff detail, edit, and delete
    path('detail/<uuid:staff_id>/', views.staff_detail, name='staff_detail'),
    path('edit/<uuid:staff_id>/', views.staff_edit, name='staff_edit'),
    path('delete/<uuid:staff_id>/', views.staff_delete, name='staff_delete'),
]
