from django.urls import path

from .views import (
    AdminNotificationSummaryView,
    NotificationClearAllView,
    NotificationListView,
    NotificationMarkAllReadView,
    NotificationMarkReadView,
    NotificationPreferenceView,
    NotificationUnreadCountView,
    RegisterPushTokenView,
)

urlpatterns = [
    path('admin/notifications/summary/', AdminNotificationSummaryView.as_view(), name='admin-notification-summary'),
    path('notifications/', NotificationListView.as_view(), name='notification-list'),
    path('notifications/unread-count/', NotificationUnreadCountView.as_view(), name='notification-unread-count'),
    path('notifications/<int:pk>/mark-read/', NotificationMarkReadView.as_view(), name='notification-mark-read'),
    path('notifications/mark-all-read/', NotificationMarkAllReadView.as_view(), name='notification-mark-all-read'),
    path('notifications/push-token/', RegisterPushTokenView.as_view(), name='notification-push-token'),
    path('notifications/preferences/', NotificationPreferenceView.as_view(), name='notification-preferences'),
    path('notifications/clear-all/', NotificationClearAllView.as_view(), name='notification-clear-all'),
]