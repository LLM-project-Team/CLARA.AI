import csv
import os
import django
from django.core.management.base import BaseCommand
from django.conf import settings
from students.models import Student, Department
from datetime import datetime

class Command(BaseCommand):
    help = 'Import students from CSV file'

    def add_arguments(self, parser):
        parser.add_argument('csv_file', type=str, help='Path to the CSV file')

    def handle(self, *args, **options):
        csv_file = options['csv_file']
        if not os.path.exists(csv_file):
            self.stdout.write(self.style.ERROR(f'File {csv_file} does not exist'))
            return

        # Get department for AIDS
        try:
            dept = Department.objects.get(name='AIDS')
        except Department.DoesNotExist:
            self.stdout.write(self.style.ERROR('Department AIDS not found'))
            return

        with open(csv_file, 'r', encoding='utf-8') as f:
            reader = csv.reader(f)
            headers = next(reader)  # Skip header
            count = 0
            skipped = 0
            for row in reader:
                row = [cell.strip() for cell in row]
                if not any(row):  # Skip empty rows
                    continue
                if len(row) < 24:
                    self.stdout.write(self.style.WARNING(f'Skipping row with insufficient columns: {len(row)} columns'))
                    continue
                try:
                    # Map columns
                    student_name = row[0].strip()
                    dob_str = row[1].strip()
                    gender = row[2].strip().upper()
                    blood_group = row[3].strip()
                    religion = row[4].strip()
                    community = row[5].strip()
                    caste = row[6].strip()
                    aadhaar = row[7].strip()
                    first_grad = row[8].strip().upper() == 'YES'
                    special_quota_str = row[9].strip()
                    has_special_quota = special_quota_str.upper() != 'NO'
                    differently_abled = row[10].strip().upper() == 'YES'
                    mobile = row[11].strip()
                    email = row[12].strip()
                    district = row[13].strip()
                    address = row[14].strip()
                    father = row[15].strip()
                    mother = row[16].strip()
                    academic_year = row[17].strip()
                    branch = row[18].strip()
                    admission_str = row[19].strip()
                    mq_gq = row[20].strip()
                    registration = row[21].strip()
                    hosteller = row[22].strip().upper() == 'YES'
                    roll_no = row[23].strip()

                    # Parse dates
                    try:
                        date_of_birth = datetime.strptime(dob_str, '%d.%m.%Y').date() if dob_str else None
                    except ValueError:
                        self.stdout.write(self.style.WARNING(f'Invalid DOB format: {dob_str}'))
                        date_of_birth = None

                    try:
                        date_of_admission = datetime.strptime(admission_str, '%d.%m.%Y').date() if admission_str else None
                    except ValueError:
                        self.stdout.write(self.style.WARNING(f'Invalid admission date format: {admission_str}'))
                        date_of_admission = None

                    # Check if student exists
                    if Student.objects.filter(roll_number=roll_no).exists():
                        self.stdout.write(self.style.WARNING(f'Student with roll {roll_no} already exists, skipping'))
                        skipped += 1
                        continue

                    # Create student
                    student = Student.objects.create(
                        college_code='2727',  # Set to valid college code
                        department_id=dept.id,
                        student_name=student_name,
                        date_of_birth=date_of_birth,
                        gender=gender,
                        blood_group=blood_group,
                        religion=religion,
                        community=community,
                        caste=caste,
                        aadhaar_number=aadhaar,
                        is_first_graduate=first_grad,
                        has_special_admission_quota=has_special_quota,
                        is_differently_abled=differently_abled,
                        mobile_number=mobile,
                        email_id=email,
                        district=district,
                        permanent_address=address,
                        father_name=father,
                        mother_name=mother,
                        academic_year_joining=academic_year,
                        branch_specialization=branch,
                        date_of_admission=date_of_admission,
                        mq_gq=mq_gq,
                        registration_number=registration,
                        hosteller=hosteller,
                        roll_number=roll_no,
                    )
                    count += 1
                    self.stdout.write(f'Created student: {student}')
                except Exception as e:
                    self.stdout.write(self.style.ERROR(f'Error processing row: {row} - {e}'))
                    continue

        self.stdout.write(self.style.SUCCESS(f'Imported {count} students, skipped {skipped} duplicates'))