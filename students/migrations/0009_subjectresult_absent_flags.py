from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('students', '0008_add_section_to_students'),
    ]

    operations = [
        migrations.AddField(
            model_name='subjectresult',
            name='internal1_absent',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='subjectresult',
            name='internal2_absent',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='subjectresult',
            name='internal3_absent',
            field=models.BooleanField(default=False),
        ),
    ]
