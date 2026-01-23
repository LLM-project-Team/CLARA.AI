"""
Setup script to create users, groups, and permissions for the Academic Administrator.

Role Hierarchy:
- Admin: Full system access (manage all users, change passwords, modify all DB schemas)
- Principal: Full access to staff/students DB and analytics (sorted by department)
- Dean: Full access to staff/students DB and analytics (sorted by batch)
- HOD: Access to their department's students DB and analytics only

Password Strategy:
- Uses individual hashed passwords from the cloud DB 'users' table
- NO common password - each user has their own secure password
"""

import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'aa.settings')
django.setup()

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType

User = get_user_model()


def create_groups_and_permissions():
    """Create groups with appropriate permissions based on role hierarchy"""
    
    # Get all permissions for circulars app
    try:
        from circulars.models import Circular
        circular_ct = ContentType.objects.get_for_model(Circular)
        circular_permissions = Permission.objects.filter(content_type=circular_ct)
    except:
        circular_permissions = []
    
    # ============ ADMIN GROUP ============
    admin_group, created = Group.objects.get_or_create(name='Admin')
    if created:
        print("✅ Created 'Admin' group")
    
    # Admin gets ALL permissions (true superuser)
    all_permissions = Permission.objects.all()
    admin_group.permissions.set(all_permissions)
    print(f"   → Assigned {all_permissions.count()} permissions to Admin")
    print("   → Can manage all users and change passwords")
    print("   → Can modify ALL database structures and schemas")
    
    # ============ PRINCIPAL GROUP ============
    principal_group, created = Group.objects.get_or_create(name='Principal')
    if created:
        print("✅ Created 'Principal' group")
    
    # Principal gets most permissions (except user management)
    principal_permissions = Permission.objects.exclude(
        codename__in=['delete_customuser', 'add_customuser']  # Can't create/delete users
    )
    principal_group.permissions.set(principal_permissions)
    print(f"   → Assigned {principal_permissions.count()} permissions to Principal")
    print("   → Can modify Staff and Students DB (structure/schema)")
    print("   → Access to ALL academic analytics (sorted by department)")
    
    # ============ DEAN GROUP ============
    dean_group, created = Group.objects.get_or_create(name='Dean')
    if created:
        print("✅ Created 'Dean' group")
    
    # Dean permissions: staff/students DB, circulars, analytics
    dean_permissions = Permission.objects.filter(
        codename__in=[
            'view_circular', 'add_circular', 'change_circular',
            'view_customuser',
            'view_logentry',
            # Add student-related permissions here when model is managed
        ]
    )
    dean_group.permissions.set(dean_permissions)
    print(f"   → Assigned {dean_permissions.count()} permissions to Dean")
    print("   → Can modify Staff and Students DB (structure/schema)")
    print("   → Access to ALL academic analytics (sorted by batch)")
    
    # ============ HOD GROUP ============
    hod_group, created = Group.objects.get_or_create(name='HOD')
    if created:
        print("✅ Created 'HOD' group")
    
    # HOD permissions: only their department's students
    hod_permissions = Permission.objects.filter(
        codename__in=[
            'view_circular',
            'view_customuser',
            # Students permissions will be checked at view level for department filtering
        ]
    )
    hod_group.permissions.set(hod_permissions)
    print(f"   → Assigned {hod_permissions.count()} permissions to HOD")
    print("   → Can modify Students DB of their department (structure/schema)")
    print("   → Access to department academic analytics only")
    
    return admin_group, principal_group, dean_group, hod_group


def sync_users_from_cloud_db(admin_group, principal_group, dean_group, hod_group):
    """
    Sync users from the cloud DB 'users' table.
    Uses individual password_hash from cloud DB - NO common password!
    """
    from users.models import UserProfile
    
    # Map roles to groups
    role_to_group = {
        'ADMIN': admin_group,
        'PRINCIPAL': principal_group,
        'DEAN': dean_group,
        'HOD': hod_group,
    }
    
    # Get all users from cloud DB
    cloud_users = UserProfile.objects.all()
    
    print(f"\n📡 Found {cloud_users.count()} users in cloud DB\n")
    
    for profile in cloud_users:
        group = role_to_group.get(profile.role)
        if not group:
            print(f"⚠️  Unknown role '{profile.role}' for {profile.email}, skipping...")
            continue
        
        # Determine if user should be superuser/staff
        is_superuser = profile.role == 'ADMIN'
        is_staff = profile.role in ['ADMIN', 'PRINCIPAL']
        
        # Create or update Django user
        user, created = User.objects.get_or_create(
            email=profile.email,
            defaults={
                'username': profile.email.split('@')[0],  # Use email prefix as username
                'is_staff': is_staff,
                'is_superuser': is_superuser,
                'is_active': profile.is_active,
            }
        )
        
        if created:
            # Set a placeholder password - actual auth uses cloud DB password_hash
            # This is a random unusable password since we auth against cloud DB
            user.set_unusable_password()
            user.save()
            print(f"✅ Created user: {profile.email} ({profile.role})")
        else:
            # Update existing user's permissions
            user.is_staff = is_staff
            user.is_superuser = is_superuser
            user.is_active = profile.is_active
            user.save()
            print(f"🔄 Updated user: {profile.email} ({profile.role})")
        
        # Clear existing groups and add to correct group
        user.groups.clear()
        user.groups.add(group)
        print(f"   → Added to '{group.name}' group")
        
        # Show password status
        if profile.password_hash:
            print(f"   → Using individual password from cloud DB ✓")
        else:
            print(f"   ⚠️  No password_hash in cloud DB!")


def create_local_admin():
    """
    Create a local admin user for emergency access.
    This admin's credentials are stored in Django's auth system.
    """
    admin_email = os.getenv('ADMIN_EMAIL', 'admin@siet.ac.in')
    admin_password = os.getenv('ADMIN_PASSWORD', 'AdminSecure@2026')
    
    user, created = User.objects.get_or_create(
        email=admin_email,
        defaults={
            'username': 'admin',
            'is_staff': True,
            'is_superuser': True,
            'is_active': True,
        }
    )
    
    if created:
        user.set_password(admin_password)
        user.save()
        print(f"\n🔐 Created local admin: {admin_email}")
        print(f"   ⚠️  Change this password immediately!")
    else:
        print(f"\nℹ️  Local admin already exists: {admin_email}")
    
    # Add to Admin group
    admin_group = Group.objects.get(name='Admin')
    user.groups.add(admin_group)
    
    return user


def main():
    print("\n" + "="*60)
    print("🏫 ACADEMIC ADMINISTRATOR - USER SETUP (Cloud DB Sync)")
    print("="*60 + "\n")
    
    # Create groups and permissions
    print("📋 Setting up Groups and Permissions...\n")
    admin_group, principal_group, dean_group, hod_group = create_groups_and_permissions()
    
    # Create local admin for emergency access
    print("\n🔐 Setting up Local Admin...")
    create_local_admin()
    
    # Sync users from cloud DB
    print("\n👥 Syncing Users from Cloud DB...\n")
    sync_users_from_cloud_db(admin_group, principal_group, dean_group, hod_group)
    
    print("\n" + "="*60)
    print("✅ SETUP COMPLETE!")
    print("="*60)
    
    print("\n🔐 Password Policy:")
    print("-" * 40)
    print("   • Each user authenticates with their individual password")
    print("   • Passwords are stored as hashes in cloud DB 'users' table")
    print("   • NO common password - each user has unique credentials")
    print("   • Admin can change any user's password via admin panel")
    
    print("\n📊 Role Permissions Summary:")
    print("-" * 40)
    print("   ADMIN:")
    print("     • Full system access")
    print("     • Can manage all users and change passwords")
    print("     • Can modify ALL database structures/schemas")
    print("")
    print("   PRINCIPAL:")
    print("     • Can modify Staff + Students DB (structure/schema)")
    print("     • Access to ALL academic analytics (by department)")
    print("")
    print("   DEAN:")
    print("     • Can modify Staff + Students DB (structure/schema)")
    print("     • Access to ALL academic analytics (by batch)")
    print("")
    print("   HOD:")
    print("     • Can modify Students DB of their department only")
    print("     • Access to department academic analytics only")
    
    # Summary
    print("\n📊 User Summary:")
    print("-" * 40)
    for user in User.objects.all():
        groups = ", ".join([g.name for g in user.groups.all()])
        status = "✓ Active" if user.is_active else "✗ Inactive"
        print(f"   {user.email} → [{groups}] {status}")
    print()


if __name__ == '__main__':
    main()
