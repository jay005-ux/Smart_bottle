from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("api", "0013_parentnotificationsetting"),
    ]

    operations = [
        migrations.AddField(
            model_name="childprofile",
            name="activity_level",
            field=models.CharField(
                choices=[("low", "Low"), ("normal", "Normal"), ("high", "High")],
                default="normal",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="childprofile",
            name="heat_sensitivity",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="childprofile",
            name="school_end",
            field=models.CharField(default="15:00", max_length=5),
        ),
        migrations.AddField(
            model_name="childprofile",
            name="school_mode_enabled",
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name="childprofile",
            name="school_start",
            field=models.CharField(default="08:00", max_length=5),
        ),
        migrations.AddField(
            model_name="childprofile",
            name="weight_kg",
            field=models.FloatField(blank=True, null=True),
        ),
    ]
