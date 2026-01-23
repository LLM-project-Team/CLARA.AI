from django.contrib.auth.backends import ModelBackend
from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import check_password
import bcrypt

User = get_user_model()


class EmailBackend(ModelBackend):
    """
    Custom backend to allow authentication using email instead of username.
    Authenticates against the password_hash stored in the cloud DB (users table).
    
    Supports both:
    - bcrypt hashed passwords (from cloud DB)
    - Django's default password hasher (for superusers created locally)
    """
    
    def authenticate(self, request, username=None, password=None, **kwargs):
        if not username or not password:
            return None
            
        try:
            user = User.objects.get(email=username)
        except User.DoesNotExist:
            return None

        # First, try to authenticate using Django's built-in password check
        # This handles superusers created via Django admin
        if user.check_password(password) and self.user_can_authenticate(user):
            return user
        
        # If Django's check fails, try to authenticate against cloud DB password_hash
        # This handles regular users whose passwords are stored in the 'users' table
        try:
            from users.models import UserProfile
            user_profile = UserProfile.get_by_email(username)
            
            if user_profile and user_profile.password_hash:
                # Check if password matches the cloud DB hash
                if self._verify_cloud_password(password, user_profile.password_hash):
                    if self.user_can_authenticate(user):
                        return user
        except Exception as e:
            # Log the error but don't expose it
            print(f"Cloud DB authentication error: {e}")
            pass
        
        return None
    
    def _verify_cloud_password(self, plain_password, hashed_password):
        """
        Verify password against the hash stored in cloud DB.
        Supports bcrypt hashes (commonly used in cloud databases).
        """
        try:
            # Check if it's a bcrypt hash (starts with $2a$, $2b$, or $2y$)
            if hashed_password.startswith(('$2a$', '$2b$', '$2y$')):
                # bcrypt verification
                return bcrypt.checkpw(
                    plain_password.encode('utf-8'),
                    hashed_password.encode('utf-8')
                )
            else:
                # Try Django's check_password for other hash formats
                return check_password(plain_password, hashed_password)
        except Exception as e:
            print(f"Password verification error: {e}")
            return False

    def get_user(self, user_id):
        try:
            return User.objects.get(pk=user_id)
        except User.DoesNotExist:
            return None
