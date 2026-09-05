from rest_framework import generics, permissions, status
from rest_framework.response import Response
from drf_spectacular.utils import extend_schema, extend_schema_view, OpenApiParameter
from django.contrib.auth import get_user_model
from .schemas import USER_LIST_SCHEMA, LOGIN_SCHEMA, REGISTER_SCHEMA, GOOGLE_LOGIN_SCHEMA
from .serializers import UserSerializer, LoginSerializer, RegisterSerializer, GoogleLoginSerializer
from apps.common.permissions import IsAdminRole
from rest_framework_simplejwt.tokens import RefreshToken

User = get_user_model()


def build_token_response(user):
    refresh = RefreshToken.for_user(user)
    refresh['role'] = getattr(user, 'role', 'USER')

    return {
        "access": str(refresh.access_token),
        "refresh": str(refresh),
        "user": UserSerializer(user).data
    }

@USER_LIST_SCHEMA
class UserListView(generics.ListAPIView):
    """
    API Mẫu: GET /api/auth/users/
    
    Format viết:
    1. Luôn khai báo permission_classes phù hợp.
    2. Override get_queryset() khi cần filter/search nâng cao.
    3. Luôn gắn decorator @extend_schema để sinh tài liệu Swagger tự động.
    """
    serializer_class = UserSerializer
    permission_classes = [IsAdminRole]

    def get_queryset(self):
        """Tùy chỉnh Queryset (Filter theo query parameter cần lấy )."""
        queryset = User.objects.all().order_by('-date_joined')
        role = self.request.query_params.get('role', None)
        
        if role:
            queryset = queryset.filter(role=role.upper())
            
        return queryset

    def list(self, request, *args, **kwargs):
        """
        Nếu cần trả thêm thông báo (message) tùy chỉnh về cho CustomJSONRenderer,
        có thể truyền dict chứa 'message' như ở dưới đây.
        """
        queryset = self.filter_queryset(self.get_queryset())

        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(queryset, many=True)
        return Response({
            "message": "Lấy danh sách người dùng thành công.",
            "results": serializer.data
        }, status=status.HTTP_200_OK)





@LOGIN_SCHEMA
class LoginView(generics.GenericAPIView):
    """
    POST /api/auth/login/
    API Đăng nhập tài khoản.
    """
    permission_classes = [permissions.AllowAny]  # Cho phép tất cả người dùng chưa đăng nhập gọi API này
    serializer_class = LoginSerializer

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        user = serializer.validated_data['user']
        
        data = build_token_response(user)

        return Response({
            "message": "Đăng nhập thành công.",
            "data": data
        }, status=status.HTTP_200_OK)


@REGISTER_SCHEMA
class RegisterView(generics.CreateAPIView):
    """
    POST /api/auth/register/
    API đăng ký tài khoản khách hàng hoặc nhân viên.
    """
    permission_classes = [permissions.AllowAny]
    serializer_class = RegisterSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        data = build_token_response(user)

        return Response({
            "message": "Đăng ký tài khoản thành công.",
            "data": data
        }, status=status.HTTP_201_CREATED)

@GOOGLE_LOGIN_SCHEMA
class GoogleLoginView(generics.GenericAPIView):
    """
    POST /api/auth/login-google/
    API đăng nhập / đăng ký bằng Google.
    """
    permission_classes = [permissions.AllowAny]
    serializer_class = GoogleLoginSerializer

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user = serializer.validated_data["user"]
        created = serializer.validated_data.get("created", False)
        data = build_token_response(user)
        data["is_new_user"] = created

        message = (
            "Đăng ký bằng Google thành công."
            if created
            else "Đăng nhập bằng Google thành công."
        )

        return Response({
            "message": message,
            "data": data
        }, status=status.HTTP_200_OK)

