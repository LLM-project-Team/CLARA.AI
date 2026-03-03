from django.core.management.base import BaseCommand
from django.utils import timezone
from students.models import Department, Student, Semester, ProgramSemester, Subject, SubjectResult, SemesterSummary
from students.views import recompute_semester_summary


class Command(BaseCommand):
    help = 'Populate sample analytics data for testing'

    def handle(self, *args, **options):
        self.stdout.write('Populating sample analytics data...')

        # Get first department
        try:
            department = Department.objects.filter(is_active=True).first()
            if not department:
                self.stdout.write(self.style.ERROR('No active departments found'))
                return
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Error getting department: {e}'))
            return

        # Get students from this department
        students = Student.objects.filter(
            department_id=department.id,
            is_active=True
        )[:10]  # Limit to 10 students for testing

        if not students:
            self.stdout.write(self.style.ERROR('No active students found in department'))
            return

        # Get all actual batch years from the database
        from django.db.models import Count
        actual_batches = Student.objects.values('academic_year_joining').distinct()
        batches_to_create = [b['academic_year_joining'] for b in actual_batches if b['academic_year_joining']]
        
        if not batches_to_create:
            self.stdout.write(self.style.WARNING('No actual batches found in student records'))
            return
        
        # Create ProgramSemester entries for ALL 8 semesters for each batch
        for batch_year in batches_to_create:
            for sem_num in range(1, 9):  # All 8 semesters
                try:
                    semester = Semester.objects.get(number=sem_num)
                    prog_sem, created = ProgramSemester.objects.get_or_create(
                        semester=semester,
                        batch_year=batch_year,
                        defaults={
                            'status': 'past' if sem_num <= 2 else ('active' if sem_num == 3 else 'upcoming'),
                        }
                    )
                    if created:
                        self.stdout.write(f'Created ProgramSemester: Batch {batch_year} - {semester}')
                except Semester.DoesNotExist:
                    self.stdout.write(self.style.WARNING(f'Semester {sem_num} not found - skipping'))
                    continue

        # Create subjects for each global semester (using batch 2023 for sample data)
        subjects_data = {
            1: [  # Sem 1
                {'code': 'CS101', 'name': 'Programming Fundamentals', 'credits': 4},
                {'code': 'MA101', 'name': 'Mathematics I', 'credits': 4},
                {'code': 'PH101', 'name': 'Physics', 'credits': 3},
            ],
            2: [  # Sem 2
                {'code': 'CS102', 'name': 'Data Structures', 'credits': 4},
                {'code': 'MA102', 'name': 'Mathematics II', 'credits': 4},
                {'code': 'CH101', 'name': 'Chemistry', 'credits': 3},
            ],
            3: [  # Sem 3
                {'code': 'CS201', 'name': 'Object Oriented Programming', 'credits': 4},
                {'code': 'CS202', 'name': 'Database Management', 'credits': 3},
                {'code': 'MA201', 'name': 'Discrete Mathematics', 'credits': 3},
            ],
        }

        for sem_num, subjects in subjects_data.items():
            try:
                semester = Semester.objects.get(number=sem_num)
                for subj_data in subjects:
                    subject, created = Subject.objects.get_or_create(
                        code=subj_data['code'],
                        defaults={
                            'name': subj_data['name'],
                            'department': department,
                            'semester': semester,
                            'credits': subj_data['credits'],
                        }
                    )
                    if created:
                        self.stdout.write(f'Created subject {subject}')
            except Semester.DoesNotExist:
                self.stdout.write(self.style.WARNING(f'Semester {sem_num} not found - skipping'))
                continue

        # Create sample results for past semesters (Sem 1 & 2)
        grade_mapping = {
            95: ('O', 10.0),
            85: ('A+', 9.0),
            75: ('A', 8.0),
            65: ('B+', 7.0),
            55: ('B', 6.0),
            45: ('C', 5.0),
            35: ('U', 0.0),
        }

        batch_year = '2023'
        for sem_num in [1, 2]:
            try:
                semester = Semester.objects.get(number=sem_num)
                prog_sem = ProgramSemester.objects.get(semester=semester, batch_year=batch_year)
                subjects = Subject.objects.filter(semester=semester, department=department)

                for student in students:
                    for subject in subjects:
                        # Generate sample marks and grades
                        import random
                        end_sem_marks = random.randint(35, 98)
                        grade, grade_points = grade_mapping.get(
                            min(grade_mapping.keys(), key=lambda x: abs(x - end_sem_marks)),
                            ('U', 0.0)
                        )

                        # Create internals
                        internals = [random.randint(15, 25) for _ in range(3)]

                        result, created = SubjectResult.objects.get_or_create(
                            student=student,
                            subject=subject,
                            defaults={
                                'internal1': internals[0],
                                'internal2': internals[1],
                                'internal3': internals[2],
                                'end_sem_marks': end_sem_marks,
                                'grade': grade,
                                'grade_points': grade_points,
                            }
                        )
                        if created:
                            self.stdout.write(f'Created result for {student.roll_number} - {subject.code}')

                # Compute semester summary
                recompute_semester_summary(prog_sem, department.id)
                self.stdout.write(f'Computed summary for Batch {batch_year} - {semester}')

            except (Semester.DoesNotExist, ProgramSemester.DoesNotExist) as e:
                self.stdout.write(self.style.WARNING(f'Error processing Sem {sem_num}: {e}'))
                continue

        self.stdout.write(self.style.SUCCESS('Sample analytics data populated successfully!'))
        self.stdout.write('You can now test the analytics workflow:')
        self.stdout.write('1. Go to Academic Analytics')
        self.stdout.write('2. Click on a department')
        self.stdout.write('3. Select a batch (2023 or 2024)')
        self.stdout.write('4. You should see 8 semester options (Sem 1-8)')
        self.stdout.write('5. For batch 2023: Sem 1-2 have sample data (click to view results)')
        self.stdout.write('6. For batch 2024: All semesters available but no sample data yet')