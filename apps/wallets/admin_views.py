from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db.models import DecimalField, F, Q, Value
from django.db.models.functions import Coalesce
from django.shortcuts import get_object_or_404
from rest_framework import generics, serializers, status
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response

from apps.bookings.models import Booking
from apps.common.distributed_lock import distributed_lock
from apps.common.idempotency import idempotent
from apps.common.permissions import IsAdminRole

from . import refund_service, wallet_service
from .models import WalletTransaction
from .serializers import WalletTransactionSerializer

User = get_user_model()
WALLET_ROLES = ('CUSTOMER', 'WORKER')


class AdminRefundSerializer(serializers.Serializer):
    amount = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=1, required=False)
    reason = serializers.CharField(max_length=500)


class AdminAdjustSerializer(serializers.Serializer):
    user_id = serializers.IntegerField()
    direction = serializers.ChoiceField(choices=['CREDIT', 'DEBIT'])
    amount = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=1)
    reason = serializers.CharField(max_length=500)
    booking_id = serializers.IntegerField(required=False, allow_null=True)


class AdminWalletTransactionSerializer(WalletTransactionSerializer):
    """Giao dịch ví kèm thông tin chủ ví, dùng cho trang theo dõi của admin."""

    booking_id = serializers.IntegerField(read_only=True, allow_null=True)
    user_id = serializers.IntegerField(source='wallet.user_id', read_only=True)
    username = serializers.CharField(source='wallet.user.username', read_only=True)
    role = serializers.CharField(source='wallet.user.role', read_only=True)
    full_name = serializers.SerializerMethodField()
    created_by_name = serializers.SerializerMethodField()

    class Meta(WalletTransactionSerializer.Meta):
        fields = WalletTransactionSerializer.Meta.fields + [
            'booking_id', 'user_id', 'username', 'full_name', 'role', 'created_by_name',
        ]

    def get_full_name(self, obj):
        user = obj.wallet.user
        return user.get_full_name() or user.username

    def get_created_by_name(self, obj):
        admin = obj.created_by
        return (admin.get_full_name() or admin.username) if admin else None


class WalletPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100


def _page_response(*, paginator, data, message):
    return Response({
        'message': message,
        'data': {
            'results': data,
            'count': paginator.page.paginator.count,
            'page': paginator.page.number,
            'total_pages': paginator.page.paginator.num_pages,
            'has_next': paginator.page.has_next(),
            'has_previous': paginator.page.has_previous(),
            'page_size': paginator.get_page_size(paginator.request),
        },
    })


def _int_param(params, name):
    raw = params.get(name)
    if not raw:
        return None
    if not raw.isdigit():
        raise serializers.ValidationError({name: 'Giá trị phải là số.'})
    return int(raw)


class AdminBookingRefundView(generics.GenericAPIView):
    permission_classes = [IsAdminRole]
    serializer_class = AdminRefundSerializer

    @idempotent
    def post(self, request, pk):
        s = self.get_serializer(data=request.data)
        s.is_valid(raise_exception=True)
        with distributed_lock(f'booking:{pk}'):
            booking, refunded = refund_service.admin_refund_booking(
                booking_id=pk, admin_user=request.user,
                reason=s.validated_data['reason'], amount=s.validated_data.get('amount'),
            )
        return Response({
            'message': 'Hoàn tiền vào ví khách hàng thành công.',
            'data': {
                'booking_id': booking.id,
                'refunded': str(refunded),
                'refunded_amount': str(booking.refunded_amount),
                'payment_status': booking.payment_status,
            },
        })


class AdminWalletAdjustView(generics.GenericAPIView):
    permission_classes = [IsAdminRole]
    serializer_class = AdminAdjustSerializer

    @idempotent
    def post(self, request):
        s = self.get_serializer(data=request.data)
        s.is_valid(raise_exception=True)
        d = s.validated_data

        user = get_object_or_404(User, pk=d['user_id'], is_active=True)
        if user.role not in WALLET_ROLES:
            raise serializers.ValidationError({'user_id': 'Chỉ điều chỉnh ví khách hàng hoặc nhân viên.'})
        booking = get_object_or_404(Booking, pk=d['booking_id']) if d.get('booking_id') else None

        tx = wallet_service.admin_adjust_wallet(
            user=user, amount=d['amount'], direction=d['direction'],
            reason=d['reason'], admin_user=request.user, booking=booking,
        )
        return Response(
            {'message': 'Điều chỉnh số dư ví thành công.', 'data': WalletTransactionSerializer(tx).data},
            status=status.HTTP_201_CREATED,
        )


class AdminUserWalletView(generics.GenericAPIView):
    permission_classes = [IsAdminRole]
    serializer_class = WalletTransactionSerializer

    def get(self, request, user_id):
        user = get_object_or_404(User, pk=user_id)
        wallet, _ = wallet_service.get_or_create_wallet(user)
        txs = (
            WalletTransaction.objects.filter(wallet=wallet)
            .select_related('booking').order_by('-created_at')[:50]
        )
        return Response({
            'message': 'Lấy thông tin ví thành công.',
            'data': {
                'user_id': user.id,
                'role': user.role,
                'balance': str(wallet.balance),
                'transactions': WalletTransactionSerializer(txs, many=True).data,
            },
        })


class AdminWalletTransactionListView(generics.GenericAPIView):
    """
    GET /api/admin/wallets/transactions/
    Lọc: search, type, direction, status, role, source (admin|system),
    user_id, booking_id. Phân trang: page, page_size.
    """

    permission_classes = [IsAdminRole]
    pagination_class = WalletPagination
    serializer_class = AdminWalletTransactionSerializer

    def get_queryset(self):
        params = self.request.query_params
        qs = WalletTransaction.objects.select_related('wallet__user', 'booking', 'created_by')

        search = params.get('search', '').strip()
        if search:
            qs = qs.filter(
                Q(wallet__user__username__icontains=search)
                | Q(wallet__user__first_name__icontains=search)
                | Q(wallet__user__last_name__icontains=search)
                | Q(wallet__user__phone_number__icontains=search)
                | Q(booking__booking_code__icontains=search)
                | Q(note__icontains=search)
            )

        for field, values in (
            ('type', WalletTransaction.Type.values),
            ('direction', WalletTransaction.Direction.values),
            ('status', WalletTransaction.Status.values),
        ):
            value = params.get(field, '').upper()
            if value:
                if value not in values:
                    raise serializers.ValidationError({field: 'Giá trị không hợp lệ.'})
                qs = qs.filter(**{field: value})

        role = params.get('role', '').upper()
        if role:
            if role not in WALLET_ROLES:
                raise serializers.ValidationError({'role': 'Giá trị không hợp lệ.'})
            qs = qs.filter(wallet__user__role=role)

        source = params.get('source', '').lower()
        if source == 'admin':
            qs = qs.filter(created_by__isnull=False)
        elif source == 'system':
            qs = qs.filter(created_by__isnull=True)
        elif source:
            raise serializers.ValidationError({'source': 'Chỉ hỗ trợ admin hoặc system.'})

        user_id = _int_param(params, 'user_id')
        if user_id:
            qs = qs.filter(wallet__user_id=user_id)
        booking_id = _int_param(params, 'booking_id')
        if booking_id:
            qs = qs.filter(booking_id=booking_id)

        return qs.order_by('-created_at', '-id')

    def get(self, request):
        paginator = self.pagination_class()
        paginator.request = request
        page = paginator.paginate_queryset(self.get_queryset(), request, view=self)
        return _page_response(
            paginator=paginator,
            data=AdminWalletTransactionSerializer(page, many=True).data,
            message='Lấy danh sách giao dịch ví thành công.',
        )


class AdminWalletTargetListView(generics.GenericAPIView):
    """
    GET /api/admin/wallets/targets/?search=&role=
    Tìm khách hàng / nhân viên kèm số dư ví để chọn người nhận điều chỉnh.
    """

    permission_classes = [IsAdminRole]
    pagination_class = WalletPagination
    serializer_class = AdminWalletTransactionSerializer

    def get(self, request):
        role = request.query_params.get('role', '').upper()
        if role and role not in WALLET_ROLES:
            raise serializers.ValidationError({'role': 'Giá trị không hợp lệ.'})

        qs = User.objects.filter(role__in=[role] if role else WALLET_ROLES, is_active=True).annotate(
            wallet_balance=Coalesce(
                F('wallet__balance'), Value(Decimal('0')),
                output_field=DecimalField(max_digits=12, decimal_places=2),
            ),
        )
        search = request.query_params.get('search', '').strip()
        if search:
            qs = qs.filter(
                Q(username__icontains=search)
                | Q(first_name__icontains=search)
                | Q(last_name__icontains=search)
                | Q(phone_number__icontains=search)
                | Q(email__icontains=search)
            )

        paginator = self.pagination_class()
        paginator.request = request
        page = paginator.paginate_queryset(qs.order_by('first_name', 'last_name', 'id'), request, view=self)
        data = [
            {
                'id': u.id,
                'name': u.get_full_name() or u.username,
                'role': u.role,
                'phone_number': getattr(u, 'phone_number', None),
                'balance': str(u.wallet_balance),
            }
            for u in page
        ]
        return _page_response(paginator=paginator, data=data, message='Tìm người dùng thành công.')