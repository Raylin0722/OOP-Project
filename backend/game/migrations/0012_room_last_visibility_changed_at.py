from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('game', '0011_room_is_public'),
    ]

    operations = [
        migrations.AddField(
            model_name='room',
            name='last_visibility_changed_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
