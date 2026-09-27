from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import (
    OpenApiExample,
    OpenApiParameter,
    extend_schema,
    inline_serializer,
)
from rest_framework import serializers

from .models import Notification
from .serializers import NotificationSerializer

notification_list_schema = extend_schema(
    tags=['Notifications'],
    summary='Danh sách thông báo của user hiện tại',
    parameters=[
        OpenApiParameter(name='is_read', type=OpenApiTypes.BOOL, location=OpenApiParameter.QUERY, required=False),
        OpenApiParameter(
            name='type', type=OpenApiTypes.STR, location=OpenApiParameter.QUERY, required=False,
            enum=[choice.value for choice in Notification.Type],
        ),
        OpenApiParameter(name='page', type=OpenApiTypes.INT, location=OpenApiParameter.QUERY, required=False),
        OpenApiParameter(name='page_size', type=OpenApiTypes.INT, location=OpenApiParameter.QUERY, required=False),
    ],
    responses={
        200: inline_serializer(
            name='NotificationListResponse',
            fields={
                'message': serializers.CharField(),
                'data': inline_serializer(
                    name='NotificationListData',
                    fields={
                        'results': NotificationSerializer(many=True),
                        'count': serializers.IntegerField(),
                        'page': serializers.IntegerField(),
                        'total_pages': serializers.IntegerField(),
                        'has_next': serializers.BooleanField(),
                        'has_previous': serializers.BooleanField(),
                        'unread_count': serializers.IntegerField(),
                    },
                ),
            },
        ),
    },
)

notification_mark_read_schema = extend_schema(
    tags=['Notifications'],
    summary='Đánh dấu 1 thông báo đã đọc',
    request=None,
    responses={
        200: inline_serializer(name='NotificationMarkReadResponse', fields={'message': serializers.CharField()}),
        404: inline_serializer(name='NotificationMarkReadNotFoundResponse', fields={'message': serializers.CharField()}),
    },
)

notification_mark_all_read_schema = extend_schema(
    tags=['Notifications'],
    summary='Đánh dấu tất cả thông báo đã đọc',
    request=None,
    responses={
        200: inline_serializer(name='NotificationMarkAllReadResponse', fields={'message': serializers.CharField()}),
    },
)

notification_unread_count_schema = extend_schema(
    tags=['Notifications'],
    summary='Lấy số thông báo chưa đọc',
    responses={
        200: inline_serializer(
            name='NotificationUnreadCountResponse',
            fields={
                'message': serializers.CharField(),
                'data': inline_serializer(
                    name='NotificationUnreadCountData',
                    fields={'unread_count': serializers.IntegerField()},
                ),
            },
        ),
    },
)