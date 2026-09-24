from django.utils import timezone

from rest_framework import generics, status
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.permissions import IsCustomerOrWorkerRole

from .models import Notification
from .serializers import NotificationSerializer


class NotificationPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 50


class NotificationListView(generics.GenericAPIView):
    permission_classes = [IsCustomerOrWorkerRole]
    serializer_class = NotificationSerializer
    pagination_class = NotificationPagination

    def get_queryset(self):
        queryset = Notification.objects.filter(user=self.request.user)

        is_read = self.request.query_params.get('is_read')
        if is_read is not None:
            queryset = queryset.filter(is_read=is_read.lower() == 'true')

        type_param = self.request.query_params.get('type')
        if type_param:
            queryset = queryset.filter(type=type_param.upper())

        return queryset

    def get(self, request, *args, **kwargs):
        queryset = self.get_queryset()
        paginator = self.pagination_class()
        page = paginator.paginate_queryset(queryset, request, view=self)

        return Response({
            'message': 'Lấy danh sách thông báo thành công.',
            'data': {
                'results': NotificationSerializer(page, many=True).data,
                'count': paginator.page.paginator.count,
                'page': paginator.page.number,
                'total_pages': paginator.page.paginator.num_pages,
                'has_next': paginator.page.has_next(),
                'has_previous': paginator.page.has_previous(),
                'unread_count': queryset.filter(is_read=False).count(),
            },
        })


class NotificationMarkReadView(APIView):
    permission_classes = [IsCustomerOrWorkerRole]

    def post(self, request, pk, *args, **kwargs):
        updated = Notification.objects.filter(
            pk=pk, user=request.user, is_read=False,
        ).update(is_read=True, read_at=timezone.now())

        if not updated:
            return Response(
                {'message': 'Không tìm thấy thông báo hoặc đã được đọc.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        return Response({'message': 'Đã đánh dấu đã đọc.'})


class NotificationMarkAllReadView(APIView):
    permission_classes = [IsCustomerOrWorkerRole]

    def post(self, request, *args, **kwargs):
        now = timezone.now()
        count = Notification.objects.filter(
            user=request.user, is_read=False,
        ).update(is_read=True, read_at=now)

        return Response({
            'message': f'Đã đánh dấu {count} thông báo đã đọc.',
        })


class NotificationUnreadCountView(APIView):
    permission_classes = [IsCustomerOrWorkerRole]

    def get(self, request, *args, **kwargs):
        count = Notification.objects.filter(user=request.user, is_read=False).count()
        return Response({'message': 'Lấy số thông báo chưa đọc thành công.', 'data': {'unread_count': count}})