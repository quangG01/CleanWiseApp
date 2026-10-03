from pathlib import Path

from django.conf import settings
from rest_framework import serializers
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema_field

from .models import Review, ReviewImage
from apps.bookings.models import BookingSchedule


@extend_schema_field(OpenApiTypes.BINARY)
class ReviewImageFileField(serializers.FileField):
    allowed_extensions = {'.jpg', '.jpeg', '.png', '.webp'}
    allowed_content_types = {'image/jpeg', 'image/png', 'image/webp'}

    def to_internal_value(self, data):
        if not hasattr(data, 'read'):
            raise serializers.ValidationError('Ảnh phải được gửi dưới dạng file.')
        extension = Path(data.name).suffix.lower()
        if extension not in self.allowed_extensions:
            raise serializers.ValidationError('Ảnh chỉ hỗ trợ JPG, JPEG, PNG hoặc WEBP.')
        content_type = getattr(data, 'content_type', '')
        if content_type and content_type not in self.allowed_content_types:
            raise serializers.ValidationError('File upload phải là ảnh hợp lệ.')
        max_size = settings.REVIEW_IMAGE_MAX_SIZE
        if data.size > max_size:
            raise serializers.ValidationError(
                f'Ảnh không được vượt quá {max_size // (1024 * 1024)}MB.'
            )
        return data


class ReviewImageSerializer(serializers.ModelSerializer):
    class Meta:
        model = ReviewImage
        fields = ['id', 'image', 'caption', 'created_at']
        read_only_fields = fields


class ReviewUserSummarySerializer(serializers.Serializer):
    id = serializers.IntegerField(read_only=True)
    username = serializers.CharField(read_only=True)
    first_name = serializers.CharField(read_only=True)
    last_name = serializers.CharField(read_only=True)
    avatar = serializers.CharField(read_only=True, allow_null=True)


class ReviewScheduleSerializer(serializers.Serializer):
    id = serializers.IntegerField(read_only=True)
    sequence_no = serializers.IntegerField(read_only=True)
    scheduled_start = serializers.DateTimeField(read_only=True)
    scheduled_end = serializers.DateTimeField(read_only=True)
    actual_start = serializers.DateTimeField(read_only=True, allow_null=True)
    actual_end = serializers.DateTimeField(read_only=True, allow_null=True)
    status = serializers.CharField(read_only=True)


class ReviewSerializer(serializers.ModelSerializer):
    assignment_id = serializers.IntegerField(read_only=True)
    booking_id = serializers.IntegerField(source='assignment.schedule.booking_id', read_only=True)
    booking_code = serializers.CharField(source='assignment.schedule.booking.booking_code', read_only=True)
    customer = ReviewUserSummarySerializer(source='assignment.schedule.booking.customer', read_only=True)
    worker = ReviewUserSummarySerializer(source='assignment.worker', read_only=True)
    schedule = ReviewScheduleSerializer(source='assignment.schedule', read_only=True)
    images = ReviewImageSerializer(many=True, read_only=True)
    service_name = serializers.CharField(source='assignment.schedule.booking.service.name', read_only=True)
    can_edit = serializers.BooleanField(read_only=True)
    edit_deadline = serializers.DateTimeField(read_only=True)
    is_edited = serializers.SerializerMethodField()
    max_images = serializers.SerializerMethodField()

    @extend_schema_field(serializers.BooleanField)
    def get_is_edited(self, instance):
        return instance.edited_at is not None

    @extend_schema_field(serializers.IntegerField)
    def get_max_images(self, instance):
        return settings.REVIEW_MAX_IMAGES

    class Meta:
        model = Review
        fields = [
            'id', 'assignment_id', 'booking_id', 'booking_code', 'schedule',
            'customer', 'worker', 'rating', 'comment', 'admin_reply',
            'replied_at', 'is_visible', 'images', 'created_at', 'updated_at',
            'service_name', 'can_edit', 'edit_deadline', 'is_edited', 'edited_at', 'max_images',
        ]
        read_only_fields = fields

class EligibleReviewAssignmentSerializer(serializers.Serializer):
    assignment_id = serializers.IntegerField(source='id', read_only=True)
    booking_id = serializers.IntegerField(source='schedule.booking_id', read_only=True)
    booking_code = serializers.CharField(source='schedule.booking.booking_code', read_only=True)
    service_name = serializers.CharField(source='schedule.booking.service.name', read_only=True)
    worker = ReviewUserSummarySerializer(read_only=True)
    schedule = ReviewScheduleSerializer(read_only=True)
    can_review = serializers.SerializerMethodField()

    @extend_schema_field(serializers.BooleanField)
    def get_can_review(self, instance):
        return instance.schedule.status == BookingSchedule.Status.COMPLETED and not hasattr(instance, 'review')


class AssignmentReviewStateSerializer(serializers.Serializer):
    assignment = EligibleReviewAssignmentSerializer(read_only=True)
    can_review = serializers.BooleanField(read_only=True)
    review = ReviewSerializer(read_only=True, allow_null=True)
    max_images = serializers.IntegerField(read_only=True)


class ReviewCreateSerializer(serializers.Serializer):
    assignment_id = serializers.IntegerField(min_value=1)
    rating = serializers.IntegerField(min_value=1, max_value=5)
    comment = serializers.CharField(required=False, allow_blank=True, allow_null=True, max_length=3000)
    images = serializers.ListField(
        child=ReviewImageFileField(),
        required=False,
        allow_empty=True,
        max_length=settings.REVIEW_MAX_IMAGES,
        write_only=True,
    )


class ReviewUpdateSerializer(serializers.Serializer):
    rating = serializers.IntegerField(required=False, min_value=1, max_value=5)
    comment = serializers.CharField(required=False, allow_blank=True, allow_null=True, max_length=3000)
    images = serializers.ListField(
        child=ReviewImageFileField(),
        required=False,
        allow_empty=True,
        max_length=settings.REVIEW_MAX_IMAGES,
        write_only=True,
    )
    delete_image_ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        required=False,
        allow_empty=True,
        write_only=True,
    )

    def validate(self, attrs):
        if not attrs:
            raise serializers.ValidationError('Cần cung cấp ít nhất một trường để cập nhật.')
        return attrs


class AdminReviewVisibilitySerializer(serializers.Serializer):
    is_visible = serializers.BooleanField()


class AdminReviewReplySerializer(serializers.Serializer):
    reply = serializers.CharField(max_length=3000, trim_whitespace=True)


class WorkerReviewSummarySerializer(serializers.Serializer):
    average_rating = serializers.DecimalField(max_digits=3, decimal_places=2, read_only=True)
    total_reviews = serializers.IntegerField(read_only=True)
    rating_distribution = serializers.DictField(
        child=serializers.IntegerField(),
        read_only=True,
    )
