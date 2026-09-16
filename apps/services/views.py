# apps/services/views.py
from rest_framework import generics, permissions, status
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response

from apps.common.permissions import IsAdminRole

from .models import Service
from .schemas import (
    ADMIN_SERVICE_DETAIL_SCHEMA,
    ADMIN_SERVICE_LIST_CREATE_SCHEMA,
    SERVICE_DETAIL_SCHEMA,
    SERVICE_LIST_SCHEMA,
)
from .serializers import (
    ServiceAdminWriteSerializer,
    ServiceDetailSerializer,
    ServiceListSerializer,
)


# ============================================================
# CUSTOMER / PUBLIC - chỉ đọc, không cần đăng nhập
# ============================================================

@SERVICE_LIST_SCHEMA
class ServiceListView(generics.ListAPIView):
    """GET /api/services/"""

    permission_classes = [permissions.AllowAny]
    serializer_class = ServiceListSerializer

    def get_queryset(self):
        queryset = Service.objects.filter(is_active=True).prefetch_related('images')
        section_code = self.request.query_params.get('section_code')
        search = self.request.query_params.get('search')
        if section_code:
            queryset = queryset.filter(section_code=section_code.strip().upper())
        if search:
            queryset = queryset.filter(name__icontains=search)
        return queryset

    def list(self, request, *args, **kwargs):
        serializer = self.get_serializer(self.get_queryset(), many=True)
        return Response({
            'message': 'Lấy danh sách dịch vụ thành công.',
            'data': serializer.data,
        }, status=status.HTTP_200_OK)


@SERVICE_DETAIL_SCHEMA
class ServiceDetailView(generics.RetrieveAPIView):
    """GET /api/services/<id>/"""

    permission_classes = [permissions.AllowAny]
    serializer_class = ServiceDetailSerializer
    queryset = Service.objects.filter(is_active=True).prefetch_related('images')

    def retrieve(self, request, *args, **kwargs):
        serializer = self.get_serializer(self.get_object())
        return Response({
            'message': 'Lấy chi tiết dịch vụ thành công.',
            'data': serializer.data,
        }, status=status.HTTP_200_OK)


# ============================================================
# ADMIN
# ============================================================

@ADMIN_SERVICE_LIST_CREATE_SCHEMA
class AdminServiceListCreateView(generics.GenericAPIView):
    """GET/POST /api/admin/services/"""

    permission_classes = [IsAdminRole]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get_serializer_class(self):
        if self.request.method == 'POST':
            return ServiceAdminWriteSerializer
        return ServiceListSerializer

    def get_queryset(self):
        queryset = Service.objects.all().prefetch_related('images')
        section_code = self.request.query_params.get('section_code')
        is_active = self.request.query_params.get('is_active')
        search = self.request.query_params.get('search')
        if section_code:
            queryset = queryset.filter(section_code=section_code.strip().upper())
        if is_active is not None:
            queryset = queryset.filter(is_active=is_active.lower() == 'true')
        if search:
            queryset = queryset.filter(name__icontains=search)
        return queryset

    def get(self, request, *args, **kwargs):
        serializer = self.get_serializer(self.get_queryset(), many=True)
        return Response({
            'message': 'Lấy danh sách dịch vụ thành công.',
            'data': serializer.data,
        }, status=status.HTTP_200_OK)

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        service = serializer.save()
        return Response({
            'message': 'Tạo dịch vụ thành công.',
            'data': ServiceDetailSerializer(service).data,
        }, status=status.HTTP_201_CREATED)


@ADMIN_SERVICE_DETAIL_SCHEMA
class AdminServiceDetailView(generics.GenericAPIView):
    """GET/PATCH/DELETE /api/admin/services/<id>/"""

    permission_classes = [IsAdminRole]
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    queryset = Service.objects.all().prefetch_related('images')

    def get_serializer_class(self):
        if self.request.method == 'PATCH':
            return ServiceAdminWriteSerializer
        return ServiceDetailSerializer

    def get(self, request, *args, **kwargs):
        return Response({
            'message': 'Lấy chi tiết dịch vụ thành công.',
            'data': ServiceDetailSerializer(self.get_object()).data,
        }, status=status.HTTP_200_OK)

    def patch(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        service = serializer.save()
        return Response({
            'message': 'Cập nhật dịch vụ thành công.',
            'data': ServiceDetailSerializer(service).data,
        }, status=status.HTTP_200_OK)

    