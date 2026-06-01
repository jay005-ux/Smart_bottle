from django.urls import path
from . import views

urlpatterns = [
    path('', views.server_info),
    path('health/', views.health),
    path('auth/signup/', views.signup),
    path('auth/login/', views.login),
    path('auth/me/', views.me),
    path('auth/change-password/', views.change_password),
    path('push-token/', views.register_push_token),
    path('notifications/', views.notifications),
    path('notification-settings/', views.notification_settings),

    path('add/', views.add_data),
    path('heartbeat/', views.heartbeat),
    path('data/', views.get_data),
    path('reset/', views.reset_data),
    path('reset-daily/', views.reset_daily_data),

    path('calibrate/', views.calibrate),
    path('calibration/', views.calibration_value),

    path('daily/', views.daily_stats),
    path('daily-15/', views.daily_goal_chart),
    path('reports/', views.parent_reports),

    path('devices/', views.devices),
    path('devices/register/', views.register_device),
    path('devices/<str:device_id>/pairing/', views.device_pairing),
    path('devices/pair/', views.pair_device),
    path('admin/devices/', views.admin_devices),
    path('admin/parents/', views.admin_parents),
    path('admin/children/', views.admin_children),
    path('admin/ownership/', views.admin_ownership),
    path('admin/devices/<str:device_id>/regenerate-pairing/', views.admin_regenerate_pairing),
    path('admin/devices/<str:device_id>/unpair/', views.admin_unpair_device),
    path('admin/devices/<str:device_id>/remove/', views.admin_remove_device),
    path('admin/devices/<str:device_id>/factory-reset/', views.admin_factory_reset_device),
    path('admin/parents/<int:user_id>/active/', views.admin_set_parent_active),
    path('admin/parents/<int:user_id>/reset-password/', views.admin_reset_parent_password),
    path('children/', views.children),
    path('children/<int:child_id>/', views.child_detail),
]
