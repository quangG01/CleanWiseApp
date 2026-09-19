from django.shortcuts import get_object_or_404
from rest_framework import generics, status
from rest_framework.exceptions import ValidationError
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response

from apps.common.permissions import IsAdminRole, IsCustomerRole, IsWorkerRole

from . import review_service
from .serializers import (
    AdminReviewReplySerializer,
    AdminReviewVisibilitySerializer,
    EligibleReviewAssignmentSerializer,
    ReviewCreateSerializer,
    ReviewSerializer,
    ReviewUpdateSerializer,
    WorkerReviewSummarySerializer,
)
from .schemas import (
    ADMIN_REVIEW_LIST_SCHEMA,
    ADMIN_REVIEW_REPLY_SCHEMA,
    ADMIN_REVIEW_VISIBILITY_SCHEMA,
    CUSTOMER_ELIGIBLE_REVIEW_SCHEMA,
    CUSTOMER_REVIEW_DETAIL_SCHEMA,
    CUSTOMER_REVIEW_LIST_CREATE_SCHEMA,
    WORKER_REVIEW_LIST_SCHEMA,
    WORKER_REVIEW_SUMMARY_SCHEMA,
)


def _filter_reviews(queryset, query_params):
    filters = {
        'rating': ('rating', 1, 5),
        'booking_id': ('assignment__schedule__booking_id', 1, None),
        'worker_id': ('assignment__worker_id', 1, None),
        'customer_id': ('assignment__schedule__booking__customer_id', 1, None),
    }
    for parameter, (lookup, minimum, maximum) in filters.items():
        raw_value = query_params.get(parameter)
        if raw_value in (None, ''):
            continue
        try:
            value = int(raw_value)
        except (TypeError, ValueError) as exc:
            raise ValidationError({parameter: 'Giá trị phải là số nguyên.'}) from exc
        if value < minimum or (maximum is not None and value > maximum):
            message = f'Giá trị phải nằm trong khoảng {minimum} đến {maximum}.' if maximum else 'Giá trị phải lớn hơn 0.'
            raise ValidationError({parameter: message})
        queryset = queryset.filter(**{lookup: value})
    return queryset


@CUSTOMER_ELIGIBLE_REVIEW_SCHEMA
class CustomerEligibleReviewListView(generics.GenericAPIView):
    permission_classes = [IsCustomerRole]
    serializer_class = EligibleReviewAssignmentSerializer

    def get(self, request, *args, **kwargs):
        queryset = review_service.eligible_assignments_for_customer(request.user)
        return Response({
            'message': 'Lấy danh sách buổi có thể đánh giá thành công.',
            'data': self.get_serializer(queryset, many=True).data,
        })


@CUSTOMER_REVIEW_LIST_CREATE_SCHEMA
class CustomerReviewListCreateView(generics.GenericAPIView):
    permission_classes = [IsCustomerRole]
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    serializer_class = ReviewSerializer

    def get_queryset(self):
        queryset = review_service.review_queryset().filter(
            assignment__schedule__booking__customer=self.request.user,
        )
        return _filter_reviews(queryset, self.request.query_params)

    def get(self, request, *args, **kwargs):
        return Response({
            'message': 'Lấy danh sách đánh giá thành công.',
            'data': self.get_serializer(self.get_queryset(), many=True).data,
        })

    def post(self, request, *args, **kwargs):
        input_serializer = ReviewCreateSerializer(data=request.data)
        input_serializer.is_valid(raise_exception=True)
        review = review_service.create_review(
            customer=request.user,
            **input_serializer.validated_data,
        )
        return Response({
            'message': 'Đánh giá nhân viên thành công.',
            'data': self.get_serializer(review).data,
        }, status=status.HTTP_201_CREATED)


@CUSTOMER_REVIEW_DETAIL_SCHEMA
class CustomerReviewDetailView(generics.GenericAPIView):
    permission_classes = [IsCustomerRole]
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    serializer_class = ReviewSerializer

    def get_object(self):
        return get_object_or_404(
            review_service.review_queryset(),
            pk=self.kwargs['pk'],
            assignment__schedule__booking__customer=self.request.user,
        )

    def get(self, request, *args, **kwargs):
        return Response({
            'message': 'Lấy chi tiết đánh giá thành công.',
            'data': self.get_serializer(self.get_object()).data,
        })

    def patch(self, request, *args, **kwargs):
        input_serializer = ReviewUpdateSerializer(data=request.data)
        input_serializer.is_valid(raise_exception=True)
        review = review_service.update_customer_review(
            review=self.get_object(),
            **input_serializer.validated_data,
        )
        return Response({
            'message': 'Cập nhật đánh giá thành công.',
            'data': self.get_serializer(review).data,
        })


@WORKER_REVIEW_LIST_SCHEMA
class WorkerReviewListView(generics.GenericAPIView):
    permission_classes = [IsWorkerRole]
    serializer_class = ReviewSerializer

    def get(self, request, *args, **kwargs):
        queryset = review_service.review_queryset().filter(
            assignment__worker=request.user,
            is_visible=True,
        )
        queryset = _filter_reviews(queryset, request.query_params)
        return Response({
            'message': 'Lấy danh sách đánh giá của nhân viên thành công.',
            'data': self.get_serializer(queryset, many=True).data,
        })


@WORKER_REVIEW_SUMMARY_SCHEMA
class WorkerReviewSummaryView(generics.GenericAPIView):
    permission_classes = [IsWorkerRole]
    serializer_class = WorkerReviewSummarySerializer

    def get(self, request, *args, **kwargs):
        return Response({
            'message': 'Lấy thống kê đánh giá thành công.',
            'data': review_service.worker_review_summary(request.user),
        })


@ADMIN_REVIEW_LIST_SCHEMA
class AdminReviewListView(generics.GenericAPIView):
    permission_classes = [IsAdminRole]
    serializer_class = ReviewSerializer

    def get(self, request, *args, **kwargs):
        queryset = _filter_reviews(review_service.review_queryset(), request.query_params)
        is_visible = request.query_params.get('is_visible')
        if is_visible is not None:
            if is_visible.lower() not in {'true', 'false'}:
                raise ValidationError({'is_visible': 'Giá trị phải là true hoặc false.'})
            queryset = queryset.filter(is_visible=is_visible.lower() == 'true')
        return Response({
            'message': 'Lấy danh sách đánh giá thành công.',
            'data': self.get_serializer(queryset, many=True).data,
        })


@ADMIN_REVIEW_VISIBILITY_SCHEMA
class AdminReviewVisibilityView(generics.GenericAPIView):
    permission_classes = [IsAdminRole]
    serializer_class = AdminReviewVisibilitySerializer

    def patch(self, request, *args, **kwargs):
        input_serializer = self.get_serializer(data=request.data)
        input_serializer.is_valid(raise_exception=True)
        review = get_object_or_404(review_service.review_queryset(), pk=kwargs['pk'])
        review = review_service.set_review_visibility(
            review=review,
            is_visible=input_serializer.validated_data['is_visible'],
        )
        return Response({
            'message': 'Cập nhật trạng thái hiển thị đánh giá thành công.',
            'data': ReviewSerializer(review).data,
        })


@ADMIN_REVIEW_REPLY_SCHEMA
class AdminReviewReplyView(generics.GenericAPIView):
    permission_classes = [IsAdminRole]
    serializer_class = AdminReviewReplySerializer

    def post(self, request, *args, **kwargs):
        input_serializer = self.get_serializer(data=request.data)
        input_serializer.is_valid(raise_exception=True)
        review = get_object_or_404(review_service.review_queryset(), pk=kwargs['pk'])
        review = review_service.reply_to_review(
            review=review,
            admin=request.user,
            reply=input_serializer.validated_data['reply'],
        )
        return Response({
            'message': 'Phản hồi đánh giá thành công.',
            'data': ReviewSerializer(review).data,
        })
