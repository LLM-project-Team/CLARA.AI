"""
Migration 0008: Add 'section' column to the unmanaged 'students' table.

Since the Student model is managed=False, we use RunSQL to ALTER the real table.
Sections are auto-populated immediately: roll-number order within each
(department_id, academic_year_joining) group → first 60 = 'A', next 60 = 'B', etc.
"""
from django.db import migrations


SECTION_SIZE = 60  # students per section


class Migration(migrations.Migration):

    dependencies = [
        ('students', '0007_end_semester_results_model'),
    ]

    operations = [
        # 1. Add column (idempotent on Postgres)
        migrations.RunSQL(
            sql="""
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_name = 'students' AND column_name = 'section'
                    ) THEN
                        ALTER TABLE students ADD COLUMN section VARCHAR(10) NULL;
                    END IF;
                END $$;
            """,
            reverse_sql="ALTER TABLE students DROP COLUMN IF EXISTS section;",
        ),
        # 2. Auto-populate sections for existing students
        migrations.RunSQL(
            sql=f"""
                UPDATE students s
                SET section = chr(64 + CEIL(ranked.row_num / {SECTION_SIZE}.0)::int)
                FROM (
                    SELECT id,
                           ROW_NUMBER() OVER (
                               PARTITION BY department_id, academic_year_joining
                               ORDER BY roll_number ASC
                           ) AS row_num
                    FROM students
                ) ranked
                WHERE s.id = ranked.id;
            """,
            reverse_sql="UPDATE students SET section = NULL;",
        ),
    ]
