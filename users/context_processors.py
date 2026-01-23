from .models import UserProfile


def user_role_context(request):
    """
    Context processor to add user_role to all templates.
    This ensures the navigation can check user role for conditional display.
    """
    if request.user.is_authenticated:
        user_profile = UserProfile.get_by_email(request.user.email)
        return {
            'user_role': user_profile.role if user_profile else 'Unknown',
            'user_profile': user_profile,
            'user_name': user_profile.name if user_profile else request.user.username,
        }
    return {
        'user_role': None,
        'user_profile': None,
        'user_name': None,
    }
