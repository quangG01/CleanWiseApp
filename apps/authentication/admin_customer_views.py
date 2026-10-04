from django.contrib.auth import get_user_model
from drf_spectacular.utils import extend_schema
from rest_framework import generics, serializers
from rest_framework.response import Response

from apps.common.permissions import IsAdminRole
from .serializers import UserSerializer

User = get_user_model()


class CustomerAccountStatusSerializer(serializers.Serializer):
    is_active = serializers.BooleanField()

    def to_internal_value(self, data):
        if not isinstance(data, dict) or set(data) != {'is_active'}:
            raise serializers.ValidationError({'non_field_errors': ['Chỉ được thay đổi trạng thái hoạt động của tài khoản.']})
        if not isinstance(data['is_active'], bool):
            raise serializers.ValidationError({'is_active': 'Giá trị phải là true hoặc false.'})
        return super().to_internal_value(data)


class AdminCustomerDetailView(generics.RetrieveAPIView):
    permission_classes = [IsAdminRole]
    serializer_class = UserSerializer
    queryset = User.objects.filter(role=User.Role.CUSTOMER)


class AdminCustomerStatusView(generics.GenericAPIView):
    permission_classes = [IsAdminRole]
    serializer_class = CustomerAccountStatusSerializer
    queryset = User.objects.filter(role=User.Role.CUSTOMER)

    @extend_schema(request=CustomerAccountStatusSerializer, responses=UserSerializer)
    def patch(self, request, pk):
        customer = self.get_object()
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        customer.is_active = serializer.validated_data['is_active']
        customer.save(update_fields=['is_active', 'updated_at'])
        return Response({
            'message': 'Cập nhật trạng thái tài khoản khách hàng thành công.',
            'data': UserSerializer(customer, context={'request': request}).data,
        })
