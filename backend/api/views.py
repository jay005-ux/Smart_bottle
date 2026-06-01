from datetime import timedelta
import secrets
import string

import requests
from django.conf import settings
from django.contrib.auth import authenticate
from django.contrib.auth.models import User
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.authtoken.models import Token
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from .models import (
    BottleDevice,
    ChildProfile,
    HydrationData,
    NotificationLog,
    ParentNotificationSetting,
    ParentProfile,
    ParentPushToken,
    generate_pairing_token,
)
from .serializers import (
    BottleDeviceSerializer,
    BottlePairingSerializer,
    ChildProfileSerializer,
    HydrationSerializer,
    NotificationLogSerializer,
    ParentNotificationSettingSerializer,
    ParentProfileSerializer,
    ParentPushTokenSerializer,
    ParentSignupSerializer,
)


def dynamic_goal_for_temperature(temp, base_goal=4000, child=None):
    goal = float(base_goal or 4000)

    if temp is None:
        return round(goal, 1)

    try:
        temp = float(temp)
    except (TypeError, ValueError):
        return round(goal, 1)

    if temp >= 45:
        goal += 1000
    if temp >= 40:
        goal += 750
    elif temp >= 38:
        goal += 500
    elif temp >= 34:
        goal += 250

    if child and child.activity_level == "high":
        goal += 250

    if child and child.heat_sensitivity and temp >= 34:
        goal += 250

    return round(goal, 1)


def is_school_time(child):
    if not child or not child.school_mode_enabled:
        return False

    now_text = timezone.localtime().strftime("%H:%M")
    start = child.school_start or "08:00"
    end = child.school_end or "15:00"

    if start <= end:
        return start <= now_text <= end

    return now_text >= start or now_text <= end


def offline_grace_seconds_for_device(device):
    if device and is_school_time(device.child):
        return 8 * 60 * 60
    return 180


def device_is_online(device, threshold_seconds=None):
    if not device or not device.last_seen:
        return False
    if threshold_seconds is None:
        threshold_seconds = offline_grace_seconds_for_device(device)
    return (timezone.now() - device.last_seen).total_seconds() <= threshold_seconds


def get_header(request, name):
    meta_name = f"HTTP_{name.upper().replace('-', '_')}"
    return request.headers.get(name) or request.META.get(meta_name)


def get_or_create_device(device_id):
    device, _ = BottleDevice.objects.get_or_create(
        device_id=device_id,
        defaults={"name": device_id.replace("_", " ").title()},
    )
    device.ensure_tokens()
    device.last_seen = timezone.now()
    device.save(update_fields=["last_seen"])
    return device


def device_ingest_allowed(request, device_id):
    provided_token = get_header(request, "X-Device-Token")
    shared_token = getattr(settings, "DEVICE_INGEST_TOKEN", "")

    if shared_token:
        return provided_token == shared_token

    if settings.ALLOW_INSECURE_DEVICE_INGEST:
        return True

    try:
        device = BottleDevice.objects.get(device_id=device_id, is_active=True)
    except BottleDevice.DoesNotExist:
        return True

    if not device.auth_token:
        return True

    return provided_token == device.auth_token


def notification_from_payload(instance):
    event = instance.event or "NORMAL"
    alert = instance.alert or ""
    device_id = instance.device_id

    if event == "DROP":
        return {
            "type": "drop",
            "title": "Bottle drop detected",
            "body": f"{device_id}: {instance.event_amount:.1f} ml dropped.",
        }

    if alert == "Bottle Empty":
        return {
            "type": "empty",
            "title": "Bottle empty",
            "body": f"{device_id}: refill the bottle.",
        }

    if alert == "Low Water":
        return {
            "type": "low_water",
            "title": "Low water",
            "body": f"{device_id}: water level is low.",
        }

    if alert == "Extreme heat - drink water and move to shade":
        return {
            "type": "extreme_heat",
            "title": "Extreme heat warning",
            "body": f"{device_id}: drink water and move to shade.",
        }

    if alert == "Drink water reminder":
        return {
            "type": "drink_reminder",
            "title": "Drink water reminder",
            "body": f"{device_id}: time for a water break.",
        }

    if alert == "Behind daily water goal":
        return {
            "type": "behind_goal",
            "title": "Behind daily goal",
            "body": f"{device_id}: hydration is behind schedule.",
        }

    return None


def build_device_report(device, days=15):
    today = timezone.localdate()
    child = device.child
    child_goal = float(child.daily_goal_ml or 4000) if child else 4000.0
    latest = (
        HydrationData.objects.filter(device_id=device.device_id)
        .order_by("-timestamp")
        .first()
    )
    daily_rows = []
    completed_days = 0
    missed_days = 0

    for offset in range(days - 1, -1, -1):
        day = today - timedelta(days=offset)
        rows = HydrationData.objects.filter(device_id=device.device_id, timestamp__date=day).order_by("timestamp")
        last = rows.last()

        intake = float(last.water_intake or 0) if last else 0.0
        goal = float(last.goal or child_goal) if last else child_goal
        completed = intake >= goal and goal > 0
        completed_days += 1 if completed else 0
        missed_days += 0 if completed else 1

        daily_rows.append({
            "date": day.isoformat(),
            "label": day.strftime("%d %b"),
            "water_intake": round(intake, 1),
            "goal": round(goal, 1),
            "completed": completed,
            "drink_count": rows.filter(event="DRINK").count(),
            "drop_count": rows.filter(event="DROP").count(),
            "fill_count": rows.filter(event="FILL").count(),
            "alerts": rows.exclude(alert__isnull=True).exclude(alert="").count(),
        })

    events = HydrationData.objects.filter(
        device_id=device.device_id,
        event__in=["FILL", "DRINK", "DROP"],
    ).order_by("-timestamp")[:25]
    alerts = HydrationData.objects.filter(
        device_id=device.device_id,
    ).exclude(alert__isnull=True).exclude(alert="").order_by("-timestamp")[:25]

    online = device_is_online(device)
    today_goal = float(latest.goal or child_goal) if latest else child_goal

    return {
        "device": BottleDeviceSerializer(device).data,
        "child": ChildProfileSerializer(child).data if child else None,
        "latest": HydrationSerializer(latest).data if latest else None,
        "is_online": online,
        "offline_seconds": (
            round((timezone.now() - device.last_seen).total_seconds(), 1)
            if device.last_seen else None
        ),
        "offline_grace_seconds": offline_grace_seconds_for_device(device),
        "school_mode_active": is_school_time(child),
        "summary": {
            "completed_days": completed_days,
            "missed_days": missed_days,
            "total_drop_events": HydrationData.objects.filter(device_id=device.device_id, event="DROP").count(),
            "total_drink_events": HydrationData.objects.filter(device_id=device.device_id, event="DRINK").count(),
            "total_alerts": HydrationData.objects.filter(device_id=device.device_id).exclude(alert__isnull=True).exclude(alert="").count(),
            "today_intake": round(float(latest.water_intake or 0), 1) if latest and latest.timestamp.date() == today else 0,
            "today_goal": round(today_goal, 1),
        },
        "days": daily_rows,
        "events": HydrationSerializer(events, many=True).data,
        "alerts": HydrationSerializer(alerts, many=True).data,
    }


def notification_enabled(parent, notification_type):
    settings_obj, _ = ParentNotificationSetting.objects.get_or_create(parent=parent)
    field_map = {
        "drop": "drop_detected",
        "empty": "bottle_empty",
        "low_water": "low_water",
        "extreme_heat": "extreme_heat",
        "drink_reminder": "drink_reminder",
        "behind_goal": "behind_goal",
    }
    field = field_map.get(notification_type)

    if field and not getattr(settings_obj, field):
        return False

    if settings_obj.quiet_hours_enabled and notification_type in {"drink_reminder", "behind_goal"}:
        now_text = timezone.localtime().strftime("%H:%M")
        start = settings_obj.quiet_start
        end = settings_obj.quiet_end

        if start <= end:
            return not (start <= now_text <= end)

        return not (now_text >= start or now_text <= end)

    return True


def send_expo_push(tokens, title, body, data=None):
    if not tokens:
        return False, "No active push tokens"

    messages = [
        {
            "to": token,
            "sound": "default",
            "title": title,
            "body": body,
            "data": data or {},
        }
        for token in tokens
    ]

    try:
        res = requests.post(settings.EXPO_PUSH_URL, json=messages, timeout=5)
        return 200 <= res.status_code < 300, res.text[:1000]
    except Exception as exc:
        return False, str(exc)


def trigger_parent_notification(instance):
    notification = notification_from_payload(instance)
    if not notification:
        return

    try:
        device = BottleDevice.objects.select_related("child", "child__parent").get(
            device_id=instance.device_id,
            child__isnull=False,
        )
    except BottleDevice.DoesNotExist:
        return

    parent = device.child.parent
    if not notification_enabled(parent, notification["type"]):
        return
    cooldown_since = timezone.now() - timedelta(seconds=settings.NOTIFICATION_COOLDOWN_SECONDS)
    already_sent = NotificationLog.objects.filter(
        parent=parent,
        device_id=instance.device_id,
        notification_type=notification["type"],
        created_at__gte=cooldown_since,
    ).exists()

    if already_sent and notification["type"] != "drop":
        return

    tokens = list(
        ParentPushToken.objects.filter(parent=parent, is_active=True)
        .values_list("token", flat=True)
    )
    delivered, expo_response = send_expo_push(
        tokens,
        notification["title"],
        notification["body"],
        data={
            "device_id": instance.device_id,
            "event": instance.event,
            "alert": instance.alert,
            "notification_type": notification["type"],
        },
    )

    NotificationLog.objects.create(
        parent=parent,
        device_id=instance.device_id,
        notification_type=notification["type"],
        title=notification["title"],
        body=notification["body"],
        event=instance.event or "",
        alert=instance.alert or "",
        delivered=delivered,
        expo_response=expo_response,
    )


@api_view(["GET"])
@permission_classes([AllowAny])
def server_info(request):
    return Response({
        "name": "Smart Bottle API",
        "status": "ok",
        "environment": settings.APP_ENVIRONMENT,
        "provider": settings.DEPLOY_PROVIDER,
        "supports": [
            "raspberry-pi-ingest",
            "multi-bottle",
            "parent-child-profiles",
            "qr-pairing",
            "aws",
            "render",
        ],
    })


@api_view(["GET"])
@permission_classes([AllowAny])
def health(request):
    return Response({
        "status": "ok",
        "time": timezone.now(),
    })


@api_view(["POST"])
@permission_classes([AllowAny])
def signup(request):
    serializer = ParentSignupSerializer(data=request.data)

    if not serializer.is_valid():
        return Response(serializer.errors, status=400)

    user = serializer.save()
    token, _ = Token.objects.get_or_create(user=user)

    return Response({
        "token": token.key,
        "parent": ParentProfileSerializer(user.parentprofile).data,
    }, status=201)


@api_view(["POST"])
@permission_classes([AllowAny])
def login(request):
    username = request.data.get("username")
    password = request.data.get("password")
    user = authenticate(username=username, password=password)

    if not user:
        return Response({"error": "Invalid username or password"}, status=400)

    profile, _ = ParentProfile.objects.get_or_create(user=user)
    token, _ = Token.objects.get_or_create(user=user)

    return Response({
        "token": token.key,
        "parent": ParentProfileSerializer(profile).data,
    })


@api_view(["GET", "PATCH"])
@permission_classes([IsAuthenticated])
def me(request):
    profile, _ = ParentProfile.objects.get_or_create(user=request.user)
    if request.method == "GET":
        return Response(ParentProfileSerializer(profile).data)

    serializer = ParentProfileSerializer(profile, data=request.data, partial=True)
    if serializer.is_valid():
        serializer.save()
        return Response(serializer.data)

    return Response(serializer.errors, status=400)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def register_push_token(request):
    token = request.data.get("token")

    if not token:
        return Response({"error": "token is required"}, status=400)

    push_token, _ = ParentPushToken.objects.update_or_create(
        token=token,
        defaults={
            "parent": request.user,
            "platform": request.data.get("platform", ""),
            "device_name": request.data.get("device_name", ""),
            "is_active": True,
        },
    )

    return Response(ParentPushTokenSerializer(push_token).data)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def notifications(request):
    rows = NotificationLog.objects.filter(parent=request.user).order_by("-created_at")[:50]
    return Response(NotificationLogSerializer(rows, many=True).data)


@api_view(["GET", "PATCH"])
@permission_classes([IsAuthenticated])
def notification_settings(request):
    settings_obj, _ = ParentNotificationSetting.objects.get_or_create(parent=request.user)

    if request.method == "GET":
        return Response(ParentNotificationSettingSerializer(settings_obj).data)

    serializer = ParentNotificationSettingSerializer(settings_obj, data=request.data, partial=True)
    if serializer.is_valid():
        serializer.save()
        return Response(serializer.data)

    return Response(serializer.errors, status=400)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def change_password(request):
    current_password = request.data.get("current_password", "")
    new_password = request.data.get("new_password", "")

    if not request.user.check_password(current_password):
        return Response({"error": "Current password is incorrect"}, status=400)

    if len(new_password) < 6:
        return Response({"error": "New password must be at least 6 characters"}, status=400)

    request.user.set_password(new_password)
    request.user.save(update_fields=["password"])
    Token.objects.filter(user=request.user).delete()

    return Response({"status": "password_changed"})


@api_view(["POST"])
@permission_classes([AllowAny])
def add_data(request):
    data = request.data.copy()
    device_id = data.get("device_id") or "bottle_01"

    if not device_ingest_allowed(request, device_id):
        return Response({"error": "Invalid device token"}, status=403)

    device = get_or_create_device(device_id)
    child = device.child
    base_goal = child.daily_goal_ml if child else 4000
    data["goal"] = dynamic_goal_for_temperature(data.get("temperature"), base_goal, child)

    serializer = HydrationSerializer(data=data)

    if serializer.is_valid():
        instance = serializer.save()
        trigger_parent_notification(instance)
        return Response({"status": "saved"})

    return Response(serializer.errors, status=400)


@api_view(["POST"])
@permission_classes([AllowAny])
def heartbeat(request):
    device_id = request.data.get("device_id") or "bottle_01"

    if not device_ingest_allowed(request, device_id):
        return Response({"error": "Invalid device token"}, status=403)

    device = get_or_create_device(device_id)
    return Response({
        "status": "heartbeat_saved",
        "device_id": device.device_id,
        "last_seen": device.last_seen,
    })


@api_view(["GET"])
@permission_classes([AllowAny])
def get_data(request):
    device_id = request.query_params.get("device_id")
    queryset = HydrationData.objects.all()

    if request.user and request.user.is_authenticated:
        owned_device_ids = BottleDevice.objects.filter(
            child__parent=request.user,
            is_active=True,
        ).values_list("device_id", flat=True)
        queryset = queryset.filter(device_id__in=owned_device_ids)

    if device_id:
        queryset = queryset.filter(device_id=device_id)

    data = queryset.order_by("-timestamp")[:100]
    serializer = HydrationSerializer(data, many=True)
    return Response(serializer.data)


@api_view(["DELETE"])
@permission_classes([AllowAny])
def reset_data(request):
    device_id = request.query_params.get("device_id")

    if request.user and request.user.is_authenticated:
        owned_device_ids = BottleDevice.objects.filter(
            child__parent=request.user,
            is_active=True,
        ).values_list("device_id", flat=True)
        queryset = HydrationData.objects.filter(device_id__in=owned_device_ids)
    elif settings.ALLOW_PUBLIC_DASHBOARD_RESET:
        queryset = HydrationData.objects.all()
    else:
        return Response({"error": "Authentication required"}, status=401)

    if device_id:
        queryset = queryset.filter(device_id=device_id)

    deleted, _ = queryset.delete()
    return Response({"status": "data cleared", "deleted": deleted})


@api_view(["DELETE"])
@permission_classes([AllowAny])
def reset_daily_data(request):
    device_id = request.query_params.get("device_id")
    today = timezone.localdate()

    if request.user and request.user.is_authenticated:
        owned_device_ids = BottleDevice.objects.filter(
            child__parent=request.user,
            is_active=True,
        ).values_list("device_id", flat=True)
        queryset = HydrationData.objects.filter(device_id__in=owned_device_ids, timestamp__date=today)
    elif settings.ALLOW_PUBLIC_DASHBOARD_RESET:
        queryset = HydrationData.objects.filter(timestamp__date=today)
    else:
        return Response({"error": "Authentication required"}, status=401)

    if device_id:
        queryset = queryset.filter(device_id=device_id)

    deleted, _ = queryset.delete()

    try:
        requests.post(f"{settings.RASPBERRY_PI_BASE_URL}/reset-daily", timeout=5)
    except Exception:
        pass

    return Response({"status": "today cleared", "deleted": deleted})


@api_view(["POST"])
@permission_classes([AllowAny])
def calibrate(request):
    try:
        res = requests.post(f"{settings.RASPBERRY_PI_BASE_URL}/calibrate", timeout=20)
        return Response(res.json())
    except Exception as e:
        return Response({"error": str(e)}, status=500)


@api_view(["GET"])
@permission_classes([AllowAny])
def calibration_value(request):
    try:
        res = requests.get(f"{settings.RASPBERRY_PI_BASE_URL}/calibration", timeout=5)
        return Response(res.json())
    except Exception as e:
        return Response({"error": str(e)}, status=500)


@api_view(["GET"])
@permission_classes([AllowAny])
def daily_stats(request):
    today = timezone.localdate()
    device_id = request.query_params.get("device_id")
    data = HydrationData.objects.filter(timestamp__date=today)

    if request.user and request.user.is_authenticated:
        owned_device_ids = BottleDevice.objects.filter(
            child__parent=request.user,
            is_active=True,
        ).values_list("device_id", flat=True)
        data = data.filter(device_id__in=owned_device_ids)

    if device_id:
        data = data.filter(device_id=device_id)

    data = data.order_by("timestamp")
    total = data.last().water_intake if data.exists() else 0

    return Response({
        "total_today": total,
        "entries": data.count(),
    })


@api_view(["GET"])
@permission_classes([AllowAny])
def daily_goal_chart(request):
    today = timezone.localdate()
    device_id = request.query_params.get("device_id")
    result = []

    for offset in range(14, -1, -1):
        day = today - timedelta(days=offset)
        rows = HydrationData.objects.filter(timestamp__date=day)

        if request.user and request.user.is_authenticated:
            owned_device_ids = BottleDevice.objects.filter(
                child__parent=request.user,
                is_active=True,
            ).values_list("device_id", flat=True)
            rows = rows.filter(device_id__in=owned_device_ids)

        if device_id:
            rows = rows.filter(device_id=device_id)

        rows = rows.order_by("timestamp")

        if rows.exists():
            last = rows.last()
            intake = float(last.water_intake or 0)
            goal = float(last.goal or 4000)
        else:
            intake = 0.0
            goal = 4000.0

        result.append({
            "date": day.isoformat(),
            "label": day.strftime("%d %b"),
            "water_intake": round(intake, 1),
            "goal": round(goal, 1),
            "completed": intake >= goal,
            "status": "Complete" if intake >= goal else "Incomplete",
        })

    return Response(result)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def parent_reports(request):
    device_id = request.query_params.get("device_id")
    devices_qs = BottleDevice.objects.filter(child__parent=request.user, is_active=True).select_related("child")

    if device_id:
        devices_qs = devices_qs.filter(device_id=device_id)

    reports = [build_device_report(device) for device in devices_qs.order_by("device_id")]

    return Response({
        "reports": reports,
        "offline_count": sum(1 for report in reports if not report["is_online"]),
        "alert_count": sum(1 for report in reports if report["latest"] and report["latest"].get("alert")),
    })


@api_view(["POST"])
@permission_classes([AllowAny])
def register_device(request):
    device_id = request.data.get("device_id")

    if not device_id:
        return Response({"error": "device_id is required"}, status=400)

    device = get_or_create_device(device_id)

    return Response({
        "device": BottleDeviceSerializer(device).data,
        "auth_token": device.auth_token,
        "pairing": BottlePairingSerializer(device).data,
    })


@api_view(["GET"])
@permission_classes([AllowAny])
def device_pairing(request, device_id):
    device = get_or_create_device(device_id)
    return Response(BottlePairingSerializer(device).data)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def pair_device(request):
    device_id = request.data.get("device_id")
    pairing_token = request.data.get("pairing_token")
    child_name = request.data.get("child_name", "Child")

    if not device_id or not pairing_token:
        return Response({"error": "device_id and pairing_token are required"}, status=400)

    try:
        device = BottleDevice.objects.get(device_id=device_id, pairing_token=pairing_token)
    except BottleDevice.DoesNotExist:
        return Response({"error": "Invalid pairing code"}, status=400)

    child, _ = ChildProfile.objects.get_or_create(
        parent=request.user,
        name=child_name,
        defaults={
            "age": request.data.get("age"),
            "school_name": request.data.get("school_name", ""),
        },
    )

    device.child = child
    device.pairing_token = ""
    device.save(update_fields=["child", "pairing_token"])

    return Response({
        "status": "paired",
        "device": BottleDeviceSerializer(device).data,
        "child": ChildProfileSerializer(child).data,
    })


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def children(request):
    if request.method == "GET":
        data = ChildProfile.objects.filter(parent=request.user).order_by("-created_at")
        return Response(ChildProfileSerializer(data, many=True).data)

    serializer = ChildProfileSerializer(data=request.data)
    if serializer.is_valid():
        serializer.save(parent=request.user)
        return Response(serializer.data, status=201)

    return Response(serializer.errors, status=400)


@api_view(["PATCH", "DELETE"])
@permission_classes([IsAuthenticated])
def child_detail(request, child_id):
    try:
        child = ChildProfile.objects.get(id=child_id, parent=request.user)
    except ChildProfile.DoesNotExist:
        return Response({"error": "Child not found"}, status=404)

    if request.method == "DELETE":
        bottles = BottleDevice.objects.filter(child=child)
        bottle_count = bottles.count()
        for bottle in bottles:
            bottle.child = None
            bottle.pairing_token = generate_pairing_token()
            bottle.save(update_fields=["child", "pairing_token"])
        child.delete()
        return Response({
            "status": "child_deleted",
            "child_id": child_id,
            "unpaired_bottles": bottle_count,
        })

    serializer = ChildProfileSerializer(child, data=request.data, partial=True)
    if serializer.is_valid():
        serializer.save()
        return Response(serializer.data)

    return Response(serializer.errors, status=400)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def devices(request):
    data = BottleDevice.objects.filter(child__parent=request.user).order_by("-created_at")
    return Response(BottleDeviceSerializer(data, many=True).data)


@api_view(["GET"])
@permission_classes([AllowAny])
def admin_devices(request):
    if not settings.ALLOW_PUBLIC_ADMIN_DASHBOARD:
        return Response({"error": "Admin dashboard authentication required"}, status=401)

    rows = []
    devices_qs = BottleDevice.objects.all().order_by("device_id")

    for device in devices_qs:
        latest = (
            HydrationData.objects.filter(device_id=device.device_id)
            .order_by("-timestamp")
            .first()
        )
        rows.append({
            "device": BottleDeviceSerializer(device).data,
            "latest": HydrationSerializer(latest).data if latest else None,
        })

    known_device_ids = set(devices_qs.values_list("device_id", flat=True))
    unregistered_ids = (
        HydrationData.objects.exclude(device_id__in=known_device_ids)
        .values_list("device_id", flat=True)
        .distinct()
    )

    for device_id in unregistered_ids:
        latest = (
            HydrationData.objects.filter(device_id=device_id)
            .order_by("-timestamp")
            .first()
        )
        rows.append({
            "device": {
                "device_id": device_id,
                "name": device_id.replace("_", " ").title(),
                "child_name": "",
                "is_active": True,
                "last_seen": latest.timestamp if latest else None,
            },
            "latest": HydrationSerializer(latest).data if latest else None,
        })

    return Response(rows)


@api_view(["GET"])
@permission_classes([AllowAny])
def admin_parents(request):
    if not settings.ALLOW_PUBLIC_ADMIN_DASHBOARD:
        return Response({"error": "Admin dashboard authentication required"}, status=401)

    parents = []
    profiles = ParentProfile.objects.select_related("user").order_by("-created_at")

    for profile in profiles:
        children_qs = ChildProfile.objects.filter(parent=profile.user)
        bottles_qs = BottleDevice.objects.filter(child__parent=profile.user)
        parents.append({
            "id": profile.id,
            "user_id": profile.user.id,
            "username": profile.user.username,
            "email": profile.user.email,
            "phone": profile.phone,
            "registered_at": profile.created_at,
            "children_count": children_qs.count(),
            "bottle_count": bottles_qs.count(),
            "is_active": profile.user.is_active,
        })

    return Response(parents)


@api_view(["GET"])
@permission_classes([AllowAny])
def admin_children(request):
    if not settings.ALLOW_PUBLIC_ADMIN_DASHBOARD:
        return Response({"error": "Admin dashboard authentication required"}, status=401)

    children_rows = []
    children_qs = ChildProfile.objects.select_related("parent").order_by("-created_at")

    for child in children_qs:
        bottles = BottleDevice.objects.filter(child=child)
        children_rows.append({
            "id": child.id,
            "name": child.name,
            "age": child.age,
            "weight_kg": child.weight_kg,
            "activity_level": child.activity_level,
            "heat_sensitivity": child.heat_sensitivity,
            "school_name": child.school_name,
            "school_start": child.school_start,
            "school_end": child.school_end,
            "school_mode_enabled": child.school_mode_enabled,
            "daily_goal_ml": child.daily_goal_ml,
            "recommended_goal_ml": ChildProfileSerializer(child).data.get("recommended_goal_ml"),
            "parent_username": child.parent.username,
            "parent_email": child.parent.email,
            "bottles": BottleDeviceSerializer(bottles, many=True).data,
            "created_at": child.created_at,
        })

    return Response(children_rows)


@api_view(["GET"])
@permission_classes([AllowAny])
def admin_ownership(request):
    if not settings.ALLOW_PUBLIC_ADMIN_DASHBOARD:
        return Response({"error": "Admin dashboard authentication required"}, status=401)

    rows = []
    devices_qs = BottleDevice.objects.select_related(
        "child",
        "child__parent",
        "child__parent__parentprofile",
    ).order_by("device_id")

    for device in devices_qs:
        latest = HydrationData.objects.filter(device_id=device.device_id).order_by("-timestamp").first()
        child = device.child
        parent = child.parent if child else None
        profile = getattr(parent, "parentprofile", None) if parent else None

        rows.append({
            "device_id": device.device_id,
            "device_name": device.name,
            "is_active": device.is_active,
            "is_online": device_is_online(device),
            "offline_grace_seconds": offline_grace_seconds_for_device(device),
            "offline_seconds": (
                round((timezone.now() - device.last_seen).total_seconds(), 1)
                if device.last_seen else None
            ),
            "last_seen": device.last_seen,
            "child_name": child.name if child else "",
            "child_age": child.age if child else None,
            "child_weight_kg": child.weight_kg if child else None,
            "activity_level": child.activity_level if child else "",
            "school_mode_active": is_school_time(child),
            "school_name": child.school_name if child else "",
            "parent_username": parent.username if parent else "",
            "parent_email": parent.email if parent else "",
            "parent_phone": profile.phone if profile else "",
            "latest": HydrationSerializer(latest).data if latest else None,
        })

    return Response(rows)


def ensure_public_admin_allowed():
    return settings.ALLOW_PUBLIC_ADMIN_DASHBOARD


def make_temp_password(length=12):
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


@api_view(["POST"])
@permission_classes([AllowAny])
def admin_regenerate_pairing(request, device_id):
    if not ensure_public_admin_allowed():
        return Response({"error": "Admin dashboard authentication required"}, status=401)

    try:
        device = BottleDevice.objects.get(device_id=device_id)
    except BottleDevice.DoesNotExist:
        return Response({"error": "Device not found"}, status=404)

    device.pairing_token = generate_pairing_token()
    device.save(update_fields=["pairing_token"])

    return Response({
        "status": "regenerated",
        "pairing": BottlePairingSerializer(device).data,
    })


@api_view(["POST"])
@permission_classes([AllowAny])
def admin_unpair_device(request, device_id):
    if not ensure_public_admin_allowed():
        return Response({"error": "Admin dashboard authentication required"}, status=401)

    try:
        device = BottleDevice.objects.get(device_id=device_id)
    except BottleDevice.DoesNotExist:
        return Response({"error": "Device not found"}, status=404)

    device.child = None
    device.pairing_token = generate_pairing_token()
    device.save(update_fields=["child", "pairing_token"])

    return Response({
        "status": "unpaired",
        "device": BottleDeviceSerializer(device).data,
        "pairing": BottlePairingSerializer(device).data,
    })


@api_view(["DELETE"])
@permission_classes([AllowAny])
def admin_remove_device(request, device_id):
    if not ensure_public_admin_allowed():
        return Response({"error": "Admin dashboard authentication required"}, status=401)

    try:
        device = BottleDevice.objects.get(device_id=device_id)
    except BottleDevice.DoesNotExist:
        deleted, _ = HydrationData.objects.filter(device_id=device_id).delete()
        return Response({
            "status": "removed_unregistered",
            "device_id": device_id,
            "deleted_readings": deleted,
        })

    deleted, _ = HydrationData.objects.filter(device_id=device_id).delete()
    device.delete()

    return Response({
        "status": "removed",
        "device_id": device_id,
        "deleted_readings": deleted,
    })


@api_view(["POST"])
@permission_classes([AllowAny])
def admin_factory_reset_device(request, device_id):
    if not ensure_public_admin_allowed():
        return Response({"error": "Admin dashboard authentication required"}, status=401)

    device = get_or_create_device(device_id)
    HydrationData.objects.filter(device_id=device_id).delete()

    device.child = None
    device.pairing_token = generate_pairing_token()
    device.ensure_tokens()
    device.save(update_fields=["child", "pairing_token"])

    pi_reset = None
    try:
        res = requests.post(f"{settings.RASPBERRY_PI_BASE_URL}/factory-reset", timeout=10)
        pi_reset = res.json()
    except Exception as exc:
        pi_reset = {"error": str(exc)}

    return Response({
        "status": "factory_reset",
        "device": BottleDeviceSerializer(device).data,
        "pairing": BottlePairingSerializer(device).data,
        "pi_reset": pi_reset,
    })


@api_view(["POST"])
@permission_classes([AllowAny])
def admin_set_parent_active(request, user_id):
    if not ensure_public_admin_allowed():
        return Response({"error": "Admin dashboard authentication required"}, status=401)

    try:
        user = User.objects.get(id=user_id)
    except User.DoesNotExist:
        return Response({"error": "Parent not found"}, status=404)

    is_active = bool(request.data.get("is_active", True))
    user.is_active = is_active
    user.save(update_fields=["is_active"])

    profile, _ = ParentProfile.objects.get_or_create(user=user)
    return Response({
        "status": "updated",
        "parent": ParentProfileSerializer(profile).data,
        "is_active": user.is_active,
    })


@api_view(["POST"])
@permission_classes([AllowAny])
def admin_reset_parent_password(request, user_id):
    if not ensure_public_admin_allowed():
        return Response({"error": "Admin dashboard authentication required"}, status=401)

    try:
        user = User.objects.get(id=user_id)
    except User.DoesNotExist:
        return Response({"error": "Parent not found"}, status=404)

    temp_password = request.data.get("temporary_password") or make_temp_password()
    user.set_password(temp_password)
    user.save(update_fields=["password"])
    Token.objects.filter(user=user).delete()

    return Response({
        "status": "password_reset",
        "username": user.username,
        "temporary_password": temp_password,
        "message": "Share this temporary password once, then ask the parent to change it.",
    })
