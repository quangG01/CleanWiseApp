from drf_spectacular.utils import extend_schema, extend_schema_view

from .serializers import (
    AdminReviewReplySerializer,
    AdminReviewVisibilitySerializer,
    EligibleReviewAssignmentSerializer,
    ReviewCreateSerializer,
    ReviewSerializer,
    ReviewUpdateSerializer,
    WorkerReviewSummarySerializer,
)


CUSTOMER_ELIGIBLE_REVIEW_SCHEMA = extend_schema_view(
    get=extend_schema(
        summary='Danh sách buổi có thể đánh giá',
        responses=EligibleReviewAssignmentSerializer(many=True),
        tags=['Review - Customer'],
    ),
)

CUSTOMER_REVIEW_LIST_CREATE_SCHEMA = extend_schema_view(
    get=extend_schema(
        summary='Danh sách đánh giá của khách hàng',
        responses=ReviewSerializer(many=True),
        tags=['Review - Customer'],
    ),
    post=extend_schema(
        summary='Đánh giá nhân viên sau khi hoàn thành buổi làm',
        request=ReviewCreateSerializer,
        responses={201: ReviewSerializer},
        tags=['Review - Customer'],
    ),
)

CUSTOMER_REVIEW_DETAIL_SCHEMA = extend_schema_view(
    get=extend_schema(
        summary='Chi tiết đánh giá của khách hàng',
        responses=ReviewSerializer,
        tags=['Review - Customer'],
    ),
    patch=extend_schema(
        summary='Cập nhật điểm hoặc bình luận đánh giá',
        request=ReviewUpdateSerializer,
        responses=ReviewSerializer,
        tags=['Review - Customer'],
    ),
)

WORKER_REVIEW_LIST_SCHEMA = extend_schema_view(
    get=extend_schema(
        summary='Danh sách đánh giá của nhân viên',
        responses=ReviewSerializer(many=True),
        tags=['Review - Worker'],
    ),
)

WORKER_REVIEW_SUMMARY_SCHEMA = extend_schema_view(
    get=extend_schema(
        summary='Thống kê điểm đánh giá của nhân viên',
        responses=WorkerReviewSummarySerializer,
        tags=['Review - Worker'],
    ),
)

ADMIN_REVIEW_LIST_SCHEMA = extend_schema_view(
    get=extend_schema(
        summary='Danh sách toàn bộ đánh giá',
        responses=ReviewSerializer(many=True),
        tags=['Review - Admin'],
    ),
)

ADMIN_REVIEW_VISIBILITY_SCHEMA = extend_schema_view(
    patch=extend_schema(
        summary='Ẩn hoặc hiện đánh giá',
        request=AdminReviewVisibilitySerializer,
        responses=ReviewSerializer,
        tags=['Review - Admin'],
    ),
)

ADMIN_REVIEW_REPLY_SCHEMA = extend_schema_view(
    post=extend_schema(
        summary='Admin phản hồi đánh giá',
        request=AdminReviewReplySerializer,
        responses=ReviewSerializer,
        tags=['Review - Admin'],
    ),
)
