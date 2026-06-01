from django.conf import settings
from django.contrib.auth.models import User
from django.utils import timezone
from rest_framework import serializers
from .models import (
    BottleDevice,
    ChildProfile,
    HydrationData,
    NotificationLog,
    ParentNotificationSetting,
    ParentProfile,
    ParentPushToken,
)


class ParentProfileSerializer(serializers.ModelSerializer):
    username = serializers.CharField(source='user.username', read_only=True)
    email = serializers.EmailField(source='user.email', required=False, allow_blank=True)

    class Meta:
        model = ParentProfile
        fields = ['id', 'username', 'email', 'phone', 'created_at']

    def update(self, instance, validated_data):
        user_data = validated_data.pop('user', {})
        email = user_data.get('email')

        if email is not None:
            instance.user.email = email
            instance.user.save(update_fields=['email'])

        return super().update(instance, validated_data)


class ParentSignupSerializer(serializers.Serializer):
    username = serializers.CharField(max_length=150)
    email = serializers.EmailField(required=False, allow_blank=True)
    password = serializers.CharField(min_length=6, write_only=True)
    phone = serializers.CharField(max_length=20, required=False, allow_blank=True)

    def validate_username(self, value):
        if User.objects.filter(username=value).exists():
            raise serializers.ValidationError("Username already exists")
        return value

    def create(self, validated_data):
        phone = validated_data.pop('phone', '')
        user = User.objects.create_user(**validated_data)
        ParentProfile.objects.create(user=user, phone=phone)
        return user


class ChildProfileSerializer(serializers.ModelSerializer):
    recommended_goal_ml = serializers.SerializerMethodField()

    class Meta:
        model = ChildProfile
        fields = [
            'id',
            'name',
            'age',
            'weight_kg',
            'activity_level',
            'heat_sensitivity',
            'school_name',
            'school_start',
            'school_end',
            'school_mode_enabled',
            'daily_goal_ml',
            'recommended_goal_ml',
            'created_at',
        ]
        read_only_fields = ['created_at']

    def get_recommended_goal_ml(self, obj):
        if obj.weight_kg:
            goal = float(obj.weight_kg) * 45
        elif obj.age:
            goal = 1600 + (max(0, min(int(obj.age), 18)) * 80)
        else:
            goal = obj.daily_goal_ml

        if obj.activity_level == 'high':
            goal += 400
        elif obj.activity_level == 'low':
            goal -= 150

        if obj.heat_sensitivity:
            goal += 250

        return round(max(1200, min(goal, 5000)), 1)


class BottleDeviceSerializer(serializers.ModelSerializer):
    child_name = serializers.CharField(source='child.name', read_only=True)
    is_online = serializers.SerializerMethodField()
    offline_seconds = serializers.SerializerMethodField()
    offline_grace_seconds = serializers.SerializerMethodField()
    school_offline_grace_active = serializers.SerializerMethodField()

    class Meta:
        model = BottleDevice
        fields = [
            'id',
            'device_id',
            'name',
            'child',
            'child_name',
            'is_active',
            'is_online',
            'offline_seconds',
            'offline_grace_seconds',
            'school_offline_grace_active',
            'last_seen',
            'created_at',
        ]
        read_only_fields = ['last_seen', 'created_at']

    def _school_mode_active(self, child):
        if not child or not child.school_mode_enabled:
            return False

        now_text = timezone.localtime().strftime("%H:%M")
        start = child.school_start or "08:00"
        end = child.school_end or "15:00"

        if start <= end:
            return start <= now_text <= end

        return now_text >= start or now_text <= end

    def _offline_grace_seconds(self, obj):
        if self._school_mode_active(obj.child):
            return 8 * 60 * 60
        return 180

    def get_is_online(self, obj):
        if not obj.last_seen:
            return False
        return (timezone.now() - obj.last_seen).total_seconds() <= self._offline_grace_seconds(obj)

    def get_offline_seconds(self, obj):
        if not obj.last_seen:
            return None
        return round((timezone.now() - obj.last_seen).total_seconds(), 1)

    def get_offline_grace_seconds(self, obj):
        return self._offline_grace_seconds(obj)

    def get_school_offline_grace_active(self, obj):
        return self._school_mode_active(obj.child)


class BottlePairingSerializer(serializers.ModelSerializer):
    pairing_payload = serializers.DictField(read_only=True)
    pairing_url = serializers.SerializerMethodField()

    class Meta:
        model = BottleDevice
        fields = ['device_id', 'name', 'pairing_payload', 'pairing_url']

    def get_pairing_url(self, obj):
        if not settings.PUBLIC_APP_URL:
            return ""

        return (
            f"{settings.PUBLIC_APP_URL.rstrip('/')}/pair"
            f"?device_id={obj.device_id}&token={obj.pairing_token}"
        )


class ParentPushTokenSerializer(serializers.ModelSerializer):
    class Meta:
        model = ParentPushToken
        fields = ['id', 'token', 'platform', 'device_name', 'is_active', 'created_at', 'updated_at']
        read_only_fields = ['created_at', 'updated_at']


class ParentNotificationSettingSerializer(serializers.ModelSerializer):
    class Meta:
        model = ParentNotificationSetting
        fields = [
            'drink_reminder',
            'behind_goal',
            'low_water',
            'bottle_empty',
            'drop_detected',
            'extreme_heat',
            'quiet_hours_enabled',
            'quiet_start',
            'quiet_end',
            'updated_at',
        ]
        read_only_fields = ['updated_at']


class NotificationLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = NotificationLog
        fields = [
            'id',
            'device_id',
            'notification_type',
            'title',
            'body',
            'event',
            'alert',
            'delivered',
            'created_at',
        ]

class HydrationSerializer(serializers.ModelSerializer):
    class Meta:
        model = HydrationData

        # ✅ EXCLUDE timestamp from input
        fields = '__all__'
        read_only_fields = ['timestamp']

    def to_internal_value(self, data):
        data = data.copy()

        water_ml = data.get('water_ml')
        if water_ml is None:
            water_ml = data.get('balance_ml')
        if water_ml is None:
            water_ml = data.get('balance')

        if water_ml is None:
            bottle_level = data.get('bottle_level') or data.get('percent')
            if bottle_level is not None:
                try:
                    water_ml = (float(bottle_level) / 100.0) * 2000.0
                except (TypeError, ValueError):
                    water_ml = 0

        if water_ml is None:
            water_ml = 0

        data['water_ml'] = water_ml
        data['balance_ml'] = data.get('balance_ml', water_ml)

        return super().to_internal_value(data)
