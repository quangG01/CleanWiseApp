from rest_framework import generics, permissions, status
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response
from drf_spectacular.utils import extend_schema, extend_schema_view, OpenApiParameter
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils import timezone
from datetime import timedelta
import secrets
from .schemas import (
    USER_LIST_SCHEMA,
    LOGIN_SCHEMA,
    REGISTER_SCHEMA,
    GOOGLE_LOGIN_SCHEMA,
    FORGOT_PASSWORD_SCHEMA,
    VERIFY_PASSWORD_RESET_OTP_SCHEMA,
    RESET_PASSWORD_SCHEMA,
    CUSTOMER_PROFILE_SCHEMA,
    WORKER_REGISTER_SCHEMA,
    WORKER_PROFILE_SCHEMA,
    ADMIN_WORKER_PROFILE_LIST_SCHEMA,
    ADMIN_WORKER_STATUS_UPDATE_SCHEMA,
)
from .serializers import (
    UserSerializer,
    CustomerProfileSerializer,
    LoginSerializer,
    RegisterSerializer,
    GoogleLoginSerializer,
    ForgotPasswordSerializer,
    VerifyPasswordResetOTPSerializer,
    ResetPasswordSerializer,
    WorkerRegisterSerializer,
    WorkerProfileUpdateSerializer,
    AdminWorkerStatusUpdateSerializer,
)
from .models import PasswordResetOTP, WorkerProfile
from apps.common.permissions import IsAdminRole, IsAdminOrCustomerRole, IsWorkerRole
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

#========================================================================================================================
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



#========================================================================================================================
@CUSTOMER_PROFILE_SCHEMA
class CustomerProfileView(generics.GenericAPIView):
    """
    GET /api/auth/customer/profile/
    PATCH /api/auth/customer/profile/
    API xem và cập nhật hồ sơ khách hàng đang đăng nhập.
    """
    permission_classes = [IsAdminOrCustomerRole]
    serializer_class = CustomerProfileSerializer
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get_object(self):
        return self.request.user

    def get(self, request, *args, **kwargs):
        serializer = self.get_serializer(self.get_object())
        return Response({
            "message": "Lấy hồ sơ khách hàng thành công.",
            "data": serializer.data
        }, status=status.HTTP_200_OK)

    def patch(self, request, *args, **kwargs):
        serializer = self.get_serializer(
            self.get_object(),
            data=request.data,
            partial=True
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()

        return Response({
            "message": "Cập nhật hồ sơ khách hàng thành công.",
            "data": serializer.data
        }, status=status.HTTP_200_OK)


#========================================================================================================================

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

#========================================================================================================================

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


#========================================================================================================================
@WORKER_REGISTER_SCHEMA
class WorkerRegisterView(generics.CreateAPIView):
    """
    POST /api/auth/worker/register/
    API đăng ký tài khoản nhân viên với trạng thái hồ sơ DRAFT.
    """
    permission_classes = [permissions.AllowAny]
    serializer_class = WorkerRegisterSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        data = build_token_response(user)
        data["profile_status"] = user.worker_profile.status

        return Response({
            "message": "Tạo tài khoản nhân viên thành công.",
            "data": data
        }, status=status.HTTP_201_CREATED)


#========================================================================================================================
@WORKER_PROFILE_SCHEMA
class WorkerProfileView(generics.GenericAPIView):
    """
    PATCH /api/auth/worker/profile/
    API cập nhật từng phần hồ sơ nhân viên đang đăng nhập.
    """
    permission_classes = [IsWorkerRole]
    serializer_class = WorkerProfileUpdateSerializer
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get_object(self):
        return self.request.user.worker_profile

    def patch(self, request, *args, **kwargs):
        previous_status = self.get_object().status
        serializer = self.get_serializer(
            self.get_object(),
            data=request.data,
            partial=True,
        )
        serializer.is_valid(raise_exception=True)
        profile = serializer.save()
        response_serializer = self.get_serializer(profile)

        message = "Cập nhật hồ sơ nhân viên thành công."
        if (
            previous_status != profile.Status.PENDING
            and profile.status == profile.Status.PENDING
        ):
            message = "Hồ sơ đã đầy đủ và được chuyển sang trạng thái chờ duyệt."

        return Response({
            "message": message,
            "data": response_serializer.data,
        }, status=status.HTTP_200_OK)


#========================================================================================================================
@ADMIN_WORKER_PROFILE_LIST_SCHEMA
class AdminWorkerProfileListView(generics.ListAPIView):
    """GET /api/auth/admin/worker-profiles/"""

    permission_classes = [IsAdminRole]
    serializer_class = WorkerProfileUpdateSerializer

    def get_queryset(self):
        requested_status = self.request.query_params.get(
            "status",
            WorkerProfile.Status.PENDING,
        ).upper()
        valid_statuses = set(WorkerProfile.Status.values)
        if requested_status not in valid_statuses:
            from rest_framework.exceptions import ValidationError
            raise ValidationError({
                "status": "Trạng thái không hợp lệ."
            })

        return (
            WorkerProfile.objects
            .filter(status=requested_status)
            .select_related("user", "approved_by")
            .prefetch_related("user__verification_documents")
            .order_by("-submitted_at", "-created_at")
        )


#========================================================================================================================
@ADMIN_WORKER_STATUS_UPDATE_SCHEMA
class AdminWorkerStatusUpdateView(generics.GenericAPIView):
    """PATCH /api/auth/admin/worker-profiles/<profile_id>/status/"""

    permission_classes = [IsAdminRole]
    serializer_class = AdminWorkerStatusUpdateSerializer
    queryset = WorkerProfile.objects.select_related("user", "approved_by")

    def patch(self, request, *args, **kwargs):
        profile = self.get_object()
        serializer = self.get_serializer(profile, data=request.data)
        serializer.is_valid(raise_exception=True)
        profile = serializer.save()

        return Response({
            "message": "Cập nhật trạng thái hồ sơ nhân viên thành công.",
            "data": WorkerProfileUpdateSerializer(profile).data,
        }, status=status.HTTP_200_OK)


#========================================================================================================================
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



#========================================================================================================================
@FORGOT_PASSWORD_SCHEMA
class ForgotPasswordView(generics.GenericAPIView):
    """
    POST /api/auth/forgot-password/
    API gửi email khôi phục mật khẩu.
    """
    permission_classes = [permissions.AllowAny]
    serializer_class = ForgotPasswordSerializer

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user = serializer.get_user()
        if user:
            code = f"{secrets.randbelow(1000000):06d}"
            PasswordResetOTP.objects.filter(
                user=user,
                used_at__isnull=True,
            ).update(used_at=timezone.now())
            PasswordResetOTP.objects.create(
                user=user,
                code_hash=PasswordResetOTP.make_code_hash(code),
                expires_at=timezone.now() + timedelta(minutes=settings.PASSWORD_RESET_OTP_TTL_MINUTES),
            )
            display_name = user.get_full_name() or user.username
            text_message = (
                "Bạn vừa yêu cầu đặt lại mật khẩu CleanWise.\n\n"
                f"Mã xác thực của bạn là: {code}\n"
                f"Mã này có hiệu lực trong {settings.PASSWORD_RESET_OTP_TTL_MINUTES} phút.\n\n"
                "Nếu bạn không yêu cầu thao tác này, vui lòng bỏ qua email này."
            )
            html_message = render_to_string(
                "emails/password_reset_otp.html",
                {
                    "code": code,
                    "ttl_minutes": settings.PASSWORD_RESET_OTP_TTL_MINUTES,
                    "display_name": display_name,
                }
            )

            email = EmailMultiAlternatives(
                subject="Khôi phục mật khẩu CleanWise",
                body=text_message,
                from_email=settings.DEFAULT_FROM_EMAIL,
                to=[user.email],
            )
            email.attach_alternative(html_message, "text/html")
            email.send(fail_silently=False)

        return Response({
            "message": "Nếu email tồn tại, hệ thống đã gửi mã xác thực khôi phục mật khẩu."
        }, status=status.HTTP_200_OK)

#========================================================================================================================
@VERIFY_PASSWORD_RESET_OTP_SCHEMA
class VerifyPasswordResetOTPView(generics.GenericAPIView):
    """
    POST /api/auth/verify-reset-otp/
    API xác minh mã OTP trước khi đặt lại mật khẩu.
    """
    permission_classes = [permissions.AllowAny]
    serializer_class = VerifyPasswordResetOTPSerializer

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()

        return Response({
            "message": "Mã xác thực hợp lệ. Bạn có thể đặt lại mật khẩu mới."
        }, status=status.HTTP_200_OK)


#========================================================================================================================
@RESET_PASSWORD_SCHEMA
class ResetPasswordView(generics.GenericAPIView):
    """
    POST /api/auth/reset-password/
    API đặt lại mật khẩu mới bằng email và mã xác thực.
    """
    permission_classes = [permissions.AllowAny]
    serializer_class = ResetPasswordSerializer

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()

        return Response({
            "message": "Đặt lại mật khẩu thành công."
        }, status=status.HTTP_200_OK)
