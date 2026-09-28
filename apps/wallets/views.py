from rest_framework import generics
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response

from apps.common.permissions import IsCustomerRole, IsWorkerRole

from apps.common.idempotency import idempotent

from . import wallet_service
from .models import Wallet, WalletTransaction
from .serializers import (
    WalletSerializer,
    WalletTransactionSerializer,
    WithdrawRequestSerializer,
)

from rest_framework.throttling import ScopedRateThrottle

class WalletTransactionPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 50


# ---------------------------------------------------------------- customer

class WalletDetailView(generics.GenericAPIView):
    """GET số dư ví của khách hàng hiện tại."""
    permission_classes = [IsCustomerRole]
    serializer_class = WalletSerializer

    def get(self, request, *args, **kwargs):
        wallet, _ = wallet_service.get_or_create_wallet(request.user)
        return Response({
            'message': 'Lấy thông tin ví thành công.',
            'data': self.get_serializer(wallet).data,
        })


class WalletTransactionListView(generics.GenericAPIView):
    """GET lịch sử giao dịch ví, phân trang."""
    permission_classes = [IsCustomerRole]
    serializer_class = WalletTransactionSerializer
    pagination_class = WalletTransactionPagination

    def get_queryset(self):
        return WalletTransaction.objects.filter(
            wallet__user=self.request.user,
        ).select_related('booking').order_by('-created_at')

    def get(self, request, *args, **kwargs):
        queryset = self.get_queryset()
        paginator = self.pagination_class()
        page = paginator.paginate_queryset(queryset, request, view=self)
        serialized = self.get_serializer(page, many=True).data
        return Response({
            'message': 'Lấy lịch sử giao dịch thành công.',
            'data': {
                'results': serialized,
                'count': paginator.page.paginator.count,
                'page': paginator.page.number,
                'total_pages': paginator.page.paginator.num_pages,
                'has_next': paginator.page.has_next(),
                'has_previous': paginator.page.has_previous(),
            },
        })


class WalletWithdrawRequestView(generics.GenericAPIView):
    """POST yêu cầu rút tiền — chờ admin duyệt."""
    permission_classes = [IsCustomerRole]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'payment'
    serializer_class = WithdrawRequestSerializer

    @idempotent
    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        tx = wallet_service.request_withdraw(
            user=request.user,
            amount=serializer.validated_data['amount'],
        )
        return Response({
            'message': 'Yêu cầu rút tiền đã được ghi nhận, chờ admin xử lý.',
            'data': WalletTransactionSerializer(tx).data,
        })


# ---------------------------------------------------------------- worker

class WorkerWalletDetailView(generics.GenericAPIView):
    """GET số dư ví ký quỹ của nhân viên hiện tại."""
    permission_classes = [IsWorkerRole]
    serializer_class = WalletSerializer

    def get(self, request, *args, **kwargs):
        wallet, _ = wallet_service.get_or_create_wallet(request.user)
        return Response({
            'message': 'Lấy thông tin ví thành công.',
            'data': self.get_serializer(wallet).data,
        })


class WorkerWalletTransactionListView(generics.GenericAPIView):
    """GET lịch sử giao dịch ví ký quỹ, phân trang."""
    permission_classes = [IsWorkerRole]
    serializer_class = WalletTransactionSerializer
    pagination_class = WalletTransactionPagination

    def get_queryset(self):
        return WalletTransaction.objects.filter(
            wallet__user=self.request.user,
        ).select_related('booking').order_by('-created_at')

    def get(self, request, *args, **kwargs):
        queryset = self.get_queryset()
        paginator = self.pagination_class()
        page = paginator.paginate_queryset(queryset, request, view=self)
        serialized = self.get_serializer(page, many=True).data
        return Response({
            'message': 'Lấy lịch sử giao dịch thành công.',
            'data': {
                'results': serialized,
                'count': paginator.page.paginator.count,
                'page': paginator.page.number,
                'total_pages': paginator.page.paginator.num_pages,
                'has_next': paginator.page.has_next(),
                'has_previous': paginator.page.has_previous(),
            },
        })


class WorkerWalletWithdrawRequestView(generics.GenericAPIView):
    """POST yêu cầu rút tiền ký quỹ — phải chừa lại tối thiểu 400.000đ, chờ admin duyệt."""
    permission_classes = [IsWorkerRole]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'payment'
    serializer_class = WithdrawRequestSerializer

    @idempotent
    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        tx = wallet_service.request_worker_withdraw(
            user=request.user,
            amount=serializer.validated_data['amount'],
        )
        return Response({
            'message': 'Yêu cầu rút tiền đã được ghi nhận, chờ admin xử lý.',
            'data': WalletTransactionSerializer(tx).data,
        })