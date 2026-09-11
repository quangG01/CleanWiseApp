from django.db import transaction
from django.utils import timezone
from rest_framework import serializers

from .models import BookingVoucher, UserVoucher, Voucher


def _validate_customer(user):
    if not user or not user.is_authenticated or getattr(user, 'role', None) != 'CUSTOMER':
        raise serializers.ValidationError({'user_id': 'Tài khoản nhận voucher phải là khách hàng.'})


def _validate_receivable_voucher(voucher, *, allow_upcoming=False):
    now = timezone.now()
    if not voucher.is_active:
        raise serializers.ValidationError({'voucher': 'Voucher đã ngừng hoạt động.'})
    if not allow_upcoming and now < voucher.start_at:
        raise serializers.ValidationError({'voucher': 'Voucher chưa đến thời gian nhận.'})
    if now > voucher.end_at:
        raise serializers.ValidationError({'voucher': 'Voucher đã hết hạn.'})
    if voucher.usage_limit is not None and voucher.used_count >= voucher.usage_limit:
        raise serializers.ValidationError({'voucher': 'Voucher đã hết lượt sử dụng.'})


def _validate_customer_usage(voucher, user):
    usage_count = BookingVoucher.objects.filter(
        voucher=voucher,
        booking__customer=user,
        status__in=[BookingVoucher.Status.RESERVED, BookingVoucher.Status.USED],
    ).count()
    if usage_count >= voucher.per_user_limit:
        raise serializers.ValidationError({
            'voucher': 'Bạn đã sử dụng hết số lượt cho voucher này.'
        })


def _get_or_create_user_voucher(*, user, voucher, source, created_by=None, admin_note=None):
    existing = (
        UserVoucher.objects.select_for_update()
        .filter(user=user, voucher=voucher)
        .first()
    )
    if existing:
        if existing.status == UserVoucher.Status.REVOKED:
            raise serializers.ValidationError({
                'voucher': 'Voucher này đã bị thu hồi và không thể tự nhận lại.'
            })
        if not existing.is_visible:
            existing.is_visible = True
            existing.save(update_fields=['is_visible', 'updated_at'])
        return existing, False

    return UserVoucher.objects.create(
        user=user,
        voucher=voucher,
        source=source,
        created_by=created_by,
        admin_note=admin_note,
    ), True


@transaction.atomic
def claim_public_voucher(*, user, voucher_id):
    _validate_customer(user)
    voucher = Voucher.objects.select_for_update().filter(pk=voucher_id).first()
    if not voucher:
        raise serializers.ValidationError({'voucher_id': 'Voucher không tồn tại.'})
    if voucher.distribution_type != Voucher.DistributionType.PUBLIC:
        raise serializers.ValidationError({
            'voucher_id': 'Voucher này không thể nhận từ danh sách công khai.'
        })
    _validate_receivable_voucher(voucher)
    _validate_customer_usage(voucher, user)
    return _get_or_create_user_voucher(
        user=user,
        voucher=voucher,
        source=UserVoucher.Source.CUSTOMER_CLAIM,
    )


@transaction.atomic
def claim_voucher_by_code(*, user, code):
    _validate_customer(user)
    normalized_code = (code or '').strip().upper()
    if not normalized_code:
        raise serializers.ValidationError({'code': 'Vui lòng nhập mã voucher.'})

    voucher = (
        Voucher.objects.select_for_update()
        .filter(code__iexact=normalized_code)
        .first()
    )
    if not voucher:
        raise serializers.ValidationError({'code': 'Mã voucher không tồn tại.'})
    if voucher.distribution_type == Voucher.DistributionType.ASSIGNED:
        raise serializers.ValidationError({'code': 'Voucher này chỉ được cấp trực tiếp.'})
    _validate_receivable_voucher(voucher)
    _validate_customer_usage(voucher, user)
    return _get_or_create_user_voucher(
        user=user,
        voucher=voucher,
        source=UserVoucher.Source.CUSTOMER_CLAIM,
    )


@transaction.atomic
def assign_voucher_to_user(*, user, voucher, admin, admin_note=None):
    _validate_customer(user)
    locked_voucher = Voucher.objects.select_for_update().get(pk=voucher.pk)
    _validate_receivable_voucher(locked_voucher, allow_upcoming=True)
    _validate_customer_usage(locked_voucher, user)

    existing = (
        UserVoucher.objects.select_for_update()
        .filter(user=user, voucher=locked_voucher)
        .first()
    )
    if existing and existing.status == UserVoucher.Status.REVOKED:
        existing.status = UserVoucher.Status.AVAILABLE
        existing.revoked_at = None
        existing.is_visible = True
        existing.source = UserVoucher.Source.ADMIN
        existing.created_by = admin
        if admin_note is not None:
            existing.admin_note = admin_note
        existing.save(update_fields=[
            'status',
            'revoked_at',
            'is_visible',
            'source',
            'created_by',
            'admin_note',
            'updated_at',
        ])
        return existing, False
    if existing:
        if admin_note is not None and admin_note != existing.admin_note:
            existing.admin_note = admin_note
            existing.save(update_fields=['admin_note', 'updated_at'])
        return existing, False

    return UserVoucher.objects.create(
        user=user,
        voucher=locked_voucher,
        source=UserVoucher.Source.ADMIN,
        created_by=admin,
        admin_note=admin_note,
    ), True


def get_user_voucher_availability(user_voucher, customer_usage_count=None):
    voucher = user_voucher.voucher
    now = timezone.now()
    if user_voucher.status == UserVoucher.Status.REVOKED:
        return 'REVOKED'
    if not voucher.is_active:
        return 'DISABLED'
    if now < voucher.start_at:
        return 'UPCOMING'
    if now > voucher.end_at:
        return 'EXPIRED'
    if voucher.usage_limit is not None and voucher.used_count >= voucher.usage_limit:
        return 'EXHAUSTED'

    if customer_usage_count is None:
        customer_usage_count = BookingVoucher.objects.filter(
            voucher=voucher,
            booking__customer=user_voucher.user,
            status__in=[BookingVoucher.Status.RESERVED, BookingVoucher.Status.USED],
        ).count()
    if customer_usage_count >= voucher.per_user_limit:
        return 'EXHAUSTED'
    return 'AVAILABLE'


@transaction.atomic
def revoke_user_voucher(user_voucher):
    locked = UserVoucher.objects.select_for_update().get(pk=user_voucher.pk)
    if locked.status != UserVoucher.Status.REVOKED:
        locked.status = UserVoucher.Status.REVOKED
        locked.revoked_at = timezone.now()
        locked.is_visible = False
        locked.save(update_fields=['status', 'revoked_at', 'is_visible', 'updated_at'])
    return locked


@transaction.atomic
def restore_user_voucher(user_voucher):
    locked = UserVoucher.objects.select_for_update().select_related('voucher').get(
        pk=user_voucher.pk
    )
    _validate_receivable_voucher(locked.voucher, allow_upcoming=True)
    locked.status = UserVoucher.Status.AVAILABLE
    locked.revoked_at = None
    locked.is_visible = True
    locked.save(update_fields=['status', 'revoked_at', 'is_visible', 'updated_at'])
    return locked
