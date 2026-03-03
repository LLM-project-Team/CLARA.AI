from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from users.models import UserProfile
from .utils import get_system_insight


@login_required
def home(request):
    """Dashboard home page showing role-based navigation"""
    user_profile = UserProfile.get_by_email(request.user.email)

    # Get dashboard features based on role
    dashboard_features = user_profile.get_dashboard_features() if user_profile else {}

    # Get AI-powered system insight
    system_insight = get_system_insight()

    context = {
        'active_page': 'dashboard',
        'user_profile': user_profile,
        'user_name': user_profile.name if user_profile else request.user.username,
        'user_role': user_profile.role if user_profile else 'Unknown',
        # Circular & AI Features (PRINCIPAL, DEAN only)
        'can_generate_circular': user_profile.can_generate_circular() if user_profile else False,
        'can_use_ai_features': user_profile.can_use_ai_features() if user_profile else False,
        # User Management (ADMIN only)
        'can_manage_users': user_profile.can_add_users() if user_profile else False,
        # Staff Database Permissions
        'can_view_staff': user_profile.can_view_staff() if user_profile else False,
        'can_modify_staff': user_profile.can_modify_staff_db() if user_profile else False,
        # Student Database Permissions (ALL users)
        'can_add_students': user_profile.can_add_students() if user_profile else False,
        'can_edit_students': user_profile.can_edit_students() if user_profile else False,
        # Academic Analytics Permissions
        'can_access_analytics': user_profile.can_access_department_analytics() if user_profile else False,
        # General
        'can_access_website_data': user_profile.can_access_website_data() if user_profile else False,
        'dashboard_features': dashboard_features,
        # AI-powered system insight
        'system_insight': system_insight,
    }
    return render(request, 'pages/home.html', context)