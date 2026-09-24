from rest_framework import generics
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response

from apps.common.permissions import IsCustomerRole

from . import wallet_service
from .models import Wallet, WalletTransaction
from .serializers import (
    WalletSerializer,
    WalletTransactionSerializer,
    WithdrawRequestSerializer,
)


class WalletTransactionPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 50


class WalletDetailView(generics.GenericAPIView):
    """GET số dư ví của khách hàng hiện tại."""
    permission_classes = [IsCustomerRole]
    serializer_class = WalletSerializer

    def get(self, request, *args, **kwargs):
        wallet, _ = Wallet.objects.get_or_create(user=request.user)
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
    serializer_class = WithdrawRequestSerializer

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