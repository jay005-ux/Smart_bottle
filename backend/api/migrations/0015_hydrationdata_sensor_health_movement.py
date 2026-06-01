from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("api", "0014_childprofile_health_school_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="hydrationdata",
            name="dht_status",
            field=models.CharField(blank=True, max_length=20, null=True),
        ),
        migrations.AddField(
            model_name="hydrationdata",
            name="movement_state",
            field=models.CharField(blank=True, max_length=20, null=True),
        ),
        migrations.AddField(
            model_name="hydrationdata",
            name="mpu_stability",
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="hydrationdata",
            name="sensor_health",
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="hydrationdata",
            name="tof_valid_percent",
            field=models.FloatField(blank=True, null=True),
        ),
    ]
