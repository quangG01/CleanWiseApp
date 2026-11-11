from datetime import timedelta
from secrets import randbelow
from uuid import uuid4

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone
from rest_framework import generics, serializers
from rest_framework.exceptions import ValidationError
from rest_framework.generics import get_object_or_404
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle

from apps.common.exceptions import ConcurrentUpdateError
from apps.common.permissions import IsAdminRole, IsWorkerRole
from apps.notifications.realtime import push_profile_review_changed
from apps.services.models import Service

from .models import PasswordResetOTP, WorkerEmailChange, WorkerProfile, WorkerProfileReviewEvent
from .serializers import WorkerProfileUpdateSerializer
from .tasks import send_otp_email

User = get_user_model()


def _profile_response(profile):
    return Response({'data': WorkerProfileUpdateSerializer(profile).data})


def _record_service(profile, actor, action, previous, proposed, reason=''):
    WorkerProfileReviewEvent.record(
        profile=profile, actor=actor, action=action, previous_status=profile.status, reason=reason,
        changes={'service': {'before': previous, 'after': proposed}},
    )
    push_profile_review_changed(profile.pk)


class WorkerServiceRequestSerializer(serializers.Serializer):
    service_id = serializers.PrimaryKeyRelatedField(queryset=Service.objects.filter(is_active=True))


class WorkerServiceRequestView(generics.GenericAPIView):
    permission_classes = [IsWorkerRole]
    serializer_class = WorkerServiceRequestSerializer

    def get(self, request):
        profile = get_object_or_404(WorkerProfile, user=request.user)
        actions = WorkerProfileReviewEvent.Action
        decision = profile.review_events.filter(action__in=(
            actions.SERVICE_APPROVED, actions.SERVICE_REJECTED,
        )).first()
        return Response({'data': {
            'action': decision.action if decision else None,
            'reason': decision.reason if decision else '',
        }})

    @transaction.atomic
    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        profile = get_object_or_404(WorkerProfile.objects.select_for_update(), user=request.user)
        service = serializer.validated_data['service_id']
        if profile.status != WorkerProfile.Status.ACTIVE:
            raise ValidationError({'service_id': 'Hồ sơ phải đang hoạt động để yêu cầu đổi dịch vụ.'})
        if profile.requested_service_id:
            raise ValidationError({'service_id': 'Bạn đã có yêu cầu đổi dịch vụ đang chờ duyệt.'})
        current = profile.registered_service
        if current and current.section_code == service.section_code:
            raise ValidationError({'service_id': 'Hãy chọn nhóm dịch vụ khác nhóm hiện tại.'})

        profile.requested_service = service
        profile.service_request_token = uuid4()
        profile.save(update_fields=['requested_service', 'service_request_token', 'updated_at'])
        _record_service(
            profile, request.user, WorkerProfileReviewEvent.Action.SERVICE_REQUESTED,
            current.name if current else None, service.name,
        )
        return _profile_response(profile)


class AdminWorkerServiceReviewSerializer(serializers.Serializer):
    request_token = serializers.UUIDField()
    decision = serializers.ChoiceField(choices=['APPROVE', 'REJECT'])
    reason = serializers.CharField(max_length=1000, required=False)

    def validate(self, attrs):
        if attrs['decision'] == 'REJECT' and not attrs.get('reason'):
            raise ValidationError({'reason': 'Vui lòng nhập lý do từ chối.'})
        return attrs


class AdminWorkerServiceReviewView(generics.GenericAPIView):
    permission_classes = [IsAdminRole]
    serializer_class = AdminWorkerServiceReviewSerializer

    @transaction.atomic
    def patch(self, request, pk):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        profile = get_object_or_404(WorkerProfile.objects.select_for_update(), pk=pk)
        data = serializer.validated_data
        if not profile.requested_service_id or data['request_token'] != profile.service_request_token:
            raise ConcurrentUpdateError('Yêu cầu đổi dịch vụ đã thay đổi. Vui lòng tải lại hồ sơ.')
        proposed = profile.requested_service
        current = profile.registered_service
        approving = data['decision'] == 'APPROVE'
        if approving:
            if profile.status != WorkerProfile.Status.ACTIVE or not proposed.is_active:
                raise ValidationError({'decision': 'Hồ sơ và dịch vụ được đề xuất phải đang hoạt động.'})
            profile.registered_service = proposed

        profile.requested_service = None
        profile.service_request_token = None
        profile.save(update_fields=['registered_service', 'requested_service', 'service_request_token', 'updated_at'])
        actions = WorkerProfileReviewEvent.Action
        _record_service(
            profile, request.user, actions.SERVICE_APPROVED if approving else actions.SERVICE_REJECTED,
            current.name if current else None, proposed.name, data.get('reason', ''),
        )
        return _profile_response(profile)


class WorkerEmailChangeRequestSerializer(serializers.Serializer):
    email = serializers.EmailField(max_length=254)
    password = serializers.CharField(write_only=True, trim_whitespace=False)


class WorkerEmailChangeConfirmSerializer(WorkerEmailChangeRequestSerializer):
    code = serializers.RegexField(r'\A[0-9]{6}\Z', write_only=True)


def _check_password(worker, password):
    if not worker.check_password(password):
        raise ValidationError({'password': 'Mật khẩu hiện tại không chính xác.'})


def _check_email_available(worker, email):
    if email == worker.email.lower():
        raise ValidationError({'email': 'Hãy nhập email khác email hiện tại.'})
    if User.objects.filter(email__iexact=email).exclude(pk=worker.pk).exists():
        raise ValidationError({'email': 'Email này đã được sử dụng.'})


class WorkerEmailChangeRequestView(generics.GenericAPIView):
    permission_classes = [IsWorkerRole]
    serializer_class = WorkerEmailChangeRequestSerializer
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'otp'

    @transaction.atomic
    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        worker = User.objects.select_for_update().get(pk=request.user.pk)
        _check_password(worker, data['password'])
        email = data['email'].lower()
        _check_email_available(worker, email)

        ttl = timedelta(minutes=settings.PASSWORD_RESET_OTP_TTL_MINUTES)
        now = timezone.now()
        existing = WorkerEmailChange.objects.filter(user=worker).first()
        if existing and now < existing.expires_at - ttl + timedelta(seconds=60):
            raise ValidationError({'code': 'Vui lòng đợi 60 giây trước khi yêu cầu gửi mã mới.'})
        code = f'{randbelow(1000000):06d}'
        WorkerEmailChange.objects.update_or_create(
            user=worker, defaults={
                'email': email, 'code_hash': WorkerEmailChange.make_code_hash(worker.pk, email, code),
                'expires_at': now + ttl, 'attempts': 0,
            },
        )
        message = f'Mã xác minh email mới của bạn là {code}. Mã có hiệu lực trong {settings.PASSWORD_RESET_OTP_TTL_MINUTES} phút.'
        transaction.on_commit(lambda: send_otp_email.delay(email, 'Xác minh email mới CleanWise', message, f'<p>{message}</p>'))
        return Response({'message': 'Đã gửi mã xác minh đến email mới.'})


class WorkerEmailChangeConfirmView(generics.GenericAPIView):
    permission_classes = [IsWorkerRole]
    serializer_class = WorkerEmailChangeConfirmSerializer
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'otp'

    @transaction.atomic
    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        worker = User.objects.select_for_update().get(pk=request.user.pk)
        _check_password(worker, data['password'])
        email = data['email'].lower()
        change = WorkerEmailChange.objects.filter(user=worker).first()
        if (
            not change or change.email != email or change.expires_at <= timezone.now()
            or change.attempts >= settings.PASSWORD_RESET_OTP_MAX_ATTEMPTS
        ):
            raise ValidationError({'code': 'Mã xác minh không hợp lệ hoặc đã hết hạn.'})
        if not change.check_code(data['code']):
            change.attempts += 1
            change.save(update_fields=['attempts'])
            return Response({'message': 'Mã xác minh không hợp lệ hoặc đã hết hạn.'}, status=400)

        _check_email_available(worker, email)
        worker.email = email
        worker.save(update_fields=['email', 'updated_at'])
        change.delete()
        PasswordResetOTP.objects.filter(user=worker, used_at__isnull=True).update(used_at=timezone.now())
        return Response({'message': 'Đã xác minh và cập nhật email.', 'data': {'email': email}})
