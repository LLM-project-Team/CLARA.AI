"""
Management command: assign_sections
------------------------------------
Assigns / re-assigns section labels (A, B, C, …) to all students in the
database based on alphabetical roll-number order within each
(department, batch) group.

  First SECTION_SIZE students  → 'A'
  Next  SECTION_SIZE students  → 'B'
  … and so on.

Usage:
    python manage.py assign_sections               # all departments / batches
    python manage.py assign_sections --section-size 60
    python manage.py assign_sections --department <dept_id>
    python manage.py assign_sections --batch 2024  # e.g. academic_year_joining startswith
"""

from django.core.management.base import BaseCommand
from django.db import connection


SECTION_SIZE = 60  # default students per section


class Command(BaseCommand):
    help = "Auto-assign section labels (A, B, C, …) to students by roll-number order."

    def add_arguments(self, parser):
        parser.add_argument(
            '--section-size', type=int, default=SECTION_SIZE,
            help=f'Number of students per section (default: {SECTION_SIZE})',
        )
        parser.add_argument(
            '--department', type=str, default=None,
            help='UUID of a specific department (default: all departments)',
        )
        parser.add_argument(
            '--batch', type=str, default=None,
            help='academic_year_joining value to restrict assignment (default: all batches)',
        )

    def handle(self, *args, **options):
        size = options['section_size']
        dept = options['department']
        batch = options['batch']

        where_clauses = []
        if dept:
            where_clauses.append(f"department_id = '{dept}'")
        if batch:
            where_clauses.append(f"academic_year_joining LIKE '{batch}%'")

        inner_where = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""
        outer_filter = ("WHERE s.id IN (SELECT id FROM students " + inner_where + ")") if where_clauses else ""

        sql = f"""
            UPDATE students s
            SET section = chr(64 + CEIL(ranked.row_num / {size}.0)::int)
            FROM (
                SELECT id,
                       ROW_NUMBER() OVER (
                           PARTITION BY department_id, academic_year_joining
                           ORDER BY roll_number ASC
                       ) AS row_num
                FROM students
                {inner_where}
            ) ranked
            WHERE s.id = ranked.id
            {('AND s.id IN (SELECT id FROM students ' + inner_where + ')') if where_clauses else ''};
        """

        with connection.cursor() as cursor:
            cursor.execute(sql)
            updated = cursor.rowcount

        self.stdout.write(
            self.style.SUCCESS(
                f"Assigned sections to {updated} student(s) "
                f"(size={size}"
                f"{', dept=' + dept if dept else ''}"
                f"{', batch=' + batch if batch else ''})."
            )
        )
