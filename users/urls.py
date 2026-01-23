from django.urls import path
from django.contrib.auth import views as auth_views
from django.http import HttpResponseRedirect
from django.views.decorators.http import require_http_methods
from . import views

app_name = 'users'

def root_redirect(request):
    # Always redirect to login page
    return HttpResponseRedirect('/login/')

@require_http_methods(["GET"])
def logout_view(request):
    """Custom logout view that handles both GET and POST requests"""
    from django.contrib.auth import logout
    logout(request)
    return HttpResponseRedirect('/login/')

urlpatterns=[
    path('', root_redirect, name='root'),
    path('login/', auth_views.LoginView.as_view(template_name='users/login.html', redirect_authenticated_user=False), name='login'),
    path('logout/', logout_view, name='logout'),
    
    # User Management (ADMIN only)
    path('manage/', views.user_management, name='user_management'),
    path('manage/add/', views.add_user, name='add_user'),
    path('manage/edit/<uuid:user_id>/', views.edit_user, name='edit_user'),
    path('manage/password/<uuid:user_id>/', views.change_password, name='change_password'),
    path('manage/delete/<uuid:user_id>/', views.delete_user, name='delete_user'),
    
    # Department Management (ADMIN only)
    path('departments/', views.department_management, name='department_management'),
    path('departments/add/', views.add_department, name='add_department'),
    path('departments/edit/<uuid:dept_id>/', views.edit_department, name='edit_department'),
    path('departments/delete/<uuid:dept_id>/', views.delete_department, name='delete_department'),
]