from django.contrib import admin

from .models import BottleDevice, ChildProfile, HydrationData, ParentProfile


@admin.register(ParentProfile)
class ParentProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "phone", "created_at")
    search_fields = ("user__username", "user__email", "phone")


@admin.register(ChildProfile)
class ChildProfileAdmin(admin.ModelAdmin):
    list_display = ("name", "parent", "age", "daily_goal_ml", "created_at")
    list_filter = ("age",)
    search_fields = ("name", "parent__username", "school_name")


@admin.register(BottleDevice)
class BottleDeviceAdmin(admin.ModelAdmin):
    list_display = ("device_id", "name", "child", "is_active", "last_seen", "created_at")
    list_filter = ("is_active",)
    search_fields = ("device_id", "name", "child__name")
    readonly_fields = ("auth_token", "pairing_token", "created_at", "last_seen")


@admin.register(HydrationData)
class HydrationDataAdmin(admin.ModelAdmin):
    list_display = (
        "device_id",
        "timestamp",
        "water_intake",
        "balance_ml",
        "event",
        "event_amount",
        "alert",
    )
    list_filter = ("device_id", "event", "alert")
    search_fields = ("device_id",)
    date_hierarchy = "timestamp"
