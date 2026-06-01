import secrets

from django.conf import settings
from django.db import models


def generate_pairing_token():
    return secrets.token_urlsafe(24)


class ParentProfile(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    phone = models.CharField(max_length=20, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.user.get_username()


class ParentNotificationSetting(models.Model):
    parent = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notification_setting",
    )
    drink_reminder = models.BooleanField(default=True)
    behind_goal = models.BooleanField(default=True)
    low_water = models.BooleanField(default=True)
    bottle_empty = models.BooleanField(default=True)
    drop_detected = models.BooleanField(default=True)
    extreme_heat = models.BooleanField(default=True)
    quiet_hours_enabled = models.BooleanField(default=False)
    quiet_start = models.CharField(max_length=5, default="21:00")
    quiet_end = models.CharField(max_length=5, default="06:00")
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.parent.username} notification settings"


class ChildProfile(models.Model):
    ACTIVITY_CHOICES = [
        ("low", "Low"),
        ("normal", "Normal"),
        ("high", "High"),
    ]

    parent = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="children",
    )
    name = models.CharField(max_length=80)
    age = models.PositiveSmallIntegerField(null=True, blank=True)
    weight_kg = models.FloatField(null=True, blank=True)
    activity_level = models.CharField(max_length=20, choices=ACTIVITY_CHOICES, default="normal")
    heat_sensitivity = models.BooleanField(default=False)
    school_name = models.CharField(max_length=120, blank=True)
    school_start = models.CharField(max_length=5, default="08:00")
    school_end = models.CharField(max_length=5, default="15:00")
    school_mode_enabled = models.BooleanField(default=True)
    daily_goal_ml = models.FloatField(default=4000)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class BottleDevice(models.Model):
    device_id = models.CharField(max_length=50, unique=True)
    name = models.CharField(max_length=80, blank=True)
    child = models.ForeignKey(
        ChildProfile,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="bottles",
    )
    auth_token = models.CharField(max_length=80, blank=True)
    pairing_token = models.CharField(max_length=80, default=generate_pairing_token)
    is_active = models.BooleanField(default=True)
    last_seen = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def ensure_tokens(self):
        changed = False
        if not self.auth_token:
            self.auth_token = secrets.token_urlsafe(32)
            changed = True
        if not self.pairing_token:
            self.pairing_token = generate_pairing_token()
            changed = True
        if changed:
            self.save(update_fields=["auth_token", "pairing_token"])

    @property
    def pairing_payload(self):
        return {
            "device_id": self.device_id,
            "pairing_token": self.pairing_token,
        }

    def __str__(self):
        return self.device_id


class ParentPushToken(models.Model):
    parent = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="push_tokens",
    )
    token = models.CharField(max_length=255, unique=True)
    platform = models.CharField(max_length=30, blank=True)
    device_name = models.CharField(max_length=120, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.parent.username} | {self.platform}"


class NotificationLog(models.Model):
    parent = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notification_logs",
    )
    device_id = models.CharField(max_length=50)
    notification_type = models.CharField(max_length=40)
    title = models.CharField(max_length=120)
    body = models.CharField(max_length=255)
    event = models.CharField(max_length=20, blank=True)
    alert = models.CharField(max_length=80, blank=True)
    delivered = models.BooleanField(default=False)
    expo_response = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.parent.username} | {self.notification_type} | {self.device_id}"


class HydrationData(models.Model):

    # -------- DEVICE -------- #
    device_id = models.CharField(max_length=50, default="bottle_01")

    # -------- BASIC DATA -------- #
    water_ml = models.FloatField(default=0)
    balance_ml = models.FloatField(default=0)
    water_intake = models.FloatField()
    goal = models.FloatField()

    temperature = models.FloatField(null=True, blank=True)
    humidity = models.FloatField(null=True, blank=True)

    bottle_level = models.FloatField()

    # -------- SENSOR DEBUG / MOTION -------- #
    direction = models.CharField(max_length=20, null=True, blank=True)
    movement_state = models.CharField(max_length=20, null=True, blank=True)
    pitch = models.FloatField(null=True, blank=True)
    roll = models.FloatField(null=True, blank=True)
    sensor_health = models.FloatField(null=True, blank=True)
    tof_valid_percent = models.FloatField(null=True, blank=True)
    mpu_stability = models.FloatField(null=True, blank=True)
    dht_status = models.CharField(max_length=20, null=True, blank=True)

    raw_current_dist = models.FloatField(null=True, blank=True)
    corrected_current_dist = models.FloatField(null=True, blank=True)
    water_height = models.FloatField(null=True, blank=True)
    raw_empty_dist = models.FloatField(null=True, blank=True)
    distance_offset = models.FloatField(null=True, blank=True)
    empty_dist = models.FloatField(null=True, blank=True)
    calibration_points_count = models.IntegerField(default=0)

    # -------- REMINDER / DROP STATE -------- #
    reminder_interval_seconds = models.FloatField(null=True, blank=True)
    last_drink_time = models.FloatField(null=True, blank=True)
    next_reminder_time = models.FloatField(null=True, blank=True)
    drop_latch_active = models.BooleanField(default=False)
    drop_latch_direction = models.CharField(max_length=20, null=True, blank=True)

    EVENT_CHOICES = [
        ("DRINK", "Drink"),
        ("FILL", "Fill"),
        ("DROP", "Drop"),
        ("NORMAL", "Normal"),
    ]
    event = models.CharField(max_length=10, choices=EVENT_CHOICES)
    event_amount = models.FloatField(default=0)

    # 🔥 NEW (IMPORTANT)
    alert = models.CharField(max_length=50, null=True, blank=True)

    # -------- TRACKING -------- #
    total_filled = models.FloatField(default=0)
    total_dropped = models.FloatField(default=0)

    fill_count = models.IntegerField(default=0)
    drop_count = models.IntegerField(default=0)

    # -------- OPTIONAL (LEGACY - KEEP) -------- #
    fill_amount = models.FloatField(default=0)
    fill_time = models.FloatField(default=0)
    drop_amount = models.FloatField(default=0)
    drop_time = models.FloatField(default=0)

    # 🔥 IMPORTANT (USE PI TIME, NOT DJANGO AUTO TIME)
    timestamp = models.DateTimeField(auto_now_add=True, null=True, blank=True)

    def __str__(self):
        return f"{self.device_id} | {self.water_intake} ml | {self.event}"
