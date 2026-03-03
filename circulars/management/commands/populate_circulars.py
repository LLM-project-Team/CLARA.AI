from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from circulars.models import Circular
from datetime import timedelta
from django.utils import timezone

User = get_user_model()

class Command(BaseCommand):
    help = 'Populate sample circulars for AI learning context'

    def handle(self, *args, **options):
        # Get or create admin user
        admin_user, created = User.objects.get_or_create(
            email='admin@siet.ac.in',
            defaults={
                'username': 'admin',
                'is_staff': True,
                'is_superuser': True
            }
        )

        if created:
            admin_user.set_password('admin@2026')
            admin_user.save()
            self.stdout.write(self.style.SUCCESS(f'Created admin user: {admin_user.email}'))

        # Sample circulars for AI learning
        sample_circulars = [
            {
                'title': 'Holiday Declaration - Pongal',
                'content': '''Subject: Holiday Declaration - Pongal

This is to inform all students, faculty, and staff that the Institute will observe a holiday on January 15, 2025, in celebration of Pongal. Regular classes and activities will resume on January 16, 2025. The Hostel Mess will remain closed on this day. We wish everyone a joyous Pongal festival filled with prosperity and happiness.''',
                'category': 'holiday'
            },
            {
                'title': 'Republic Day Holiday Notice',
                'content': '''Subject: Republic Day Holiday Declaration

The Institute will observe a holiday on January 26, 2025, to commemorate Republic Day. All academic activities, administrative offices, and hostel facilities will remain closed. Regular schedule will resume from January 27, 2025. Let us celebrate this occasion with pride and patriotism.''',
                'category': 'holiday'
            },
            {
                'title': 'Mid-Semester Examination Schedule',
                'content': '''Subject: Mid-Semester Examination Schedule

This is to inform all students that the Mid-Semester examinations for the current semester will commence from November 15, 2024. Students are required to report to their examination halls 15 minutes before the scheduled time. Carrying of mobile phones and electronic devices is strictly prohibited. Any malpractice will result in severe disciplinary action.''',
                'category': 'manual'
            },
            {
                'title': 'Lab Uniform Compliance Reminder',
                'content': '''Subject: Lab Uniform - Strict Compliance

This circular serves as a reminder to all students regarding the mandatory wearing of lab uniforms during laboratory sessions. It has been observed that some students are not adhering to this policy. Students found without proper lab uniform will not be permitted to enter the laboratory. Your cooperation in maintaining discipline is appreciated.''',
                'category': 'manual'
            },
            {
                'title': 'Hostel Fee Payment Deadline',
                'content': '''Subject: Hostel Fee Payment Deadline

All hostel students are hereby informed that the last date for payment of hostel fees for the current semester is December 15, 2024. Students who fail to pay the fees by this date will face discontinuation of mess facilities. Please complete all fee formalities at the earliest to avoid inconvenience.''',
                'category': 'manual'
            }
        ]

        created_count = 0
        for i, circ_data in enumerate(sample_circulars):
            # Create circulars with different timestamps (older first)
            created_at = timezone.now() - timedelta(days=30-i*5)

            circular, created = Circular.objects.get_or_create(
                title=circ_data['title'],
                defaults={
                    'user': admin_user,
                    'content': circ_data['content'],
                    'category': circ_data['category']
                }
            )

            if created:
                # Update created_at for proper ordering
                circular.created_at = created_at
                circular.save(update_fields=['created_at'])
                created_count += 1
                self.stdout.write(self.style.SUCCESS(f'Created: {circ_data["title"]}'))

        self.stdout.write(self.style.SUCCESS(f'Successfully created {created_count} sample circulars for AI learning context'))
        self.stdout.write(self.style.WARNING('AI system will now learn from these examples to generate more accurate circulars'))