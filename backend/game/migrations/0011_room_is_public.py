# Generated manually for public room lobby support

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('game', '0010_matchmakingticket_source_room_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='room',
            name='is_public',
            field=models.BooleanField(default=False),
        ),
    ]
