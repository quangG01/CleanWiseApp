from rest_framework import generics, permissions, status
from rest_framework.exceptions import ValidationError
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response
from drf_spectacular.types import OpenApiTypes 
from drf_spectacular.utils import extend_schema, extend_schema_view, OpenApiParameter
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from django.template.loader import render_to_string
from django.utils import timezone
from datetime import timedelta

import jwt as pyjwt
from rest_framework_simplejwt.views import TokenRefreshView
from rest_framework_simplejwt.serializers import TokenRefreshSerializer
from rest_framework_simplejwt.token_blacklist.models import OutstandingToken
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError

from rest_framework.throttling import ScopedRateThrottle
from apps.notifications.models import DeviceToken

import secrets
from .schemas import (
    USER_LIST_SCHEMA,
    LOGIN_SCHEMA,
    CUSTOMER_REGISTER_SCHEMA,
    GOOGLE_LOGIN_SCHEMA,
    FORGOT_PASSWORD_SCHEMA,
    VERIFY_PASSWORD_RESET_OTP_SCHEMA,
    RESET_PASSWORD_SCHEMA,
    CUSTOMER_PROFILE_SCHEMA,
    WORKER_REGISTER_SCHEMA,
    WORKER_PROFILE_SCHEMA,
    WORKER_PROFILE_SUBMIT_SCHEMA,
    ADMIN_WORKER_PROFILE_LIST_SCHEMA,
    ADMIN_WORKER_STATUS_UPDATE_SCHEMA,
)
from .serializers import (
    UserSerializer,
    CustomerProfileSerializer,
    LoginSerializer,
    CustomerRegisterSerializer,
    GoogleLoginSerializer,
    ForgotPasswordSerializer,
    VerifyPasswordResetOTPSerializer,
    ResetPasswordSerializer,
    ChangePasswordSerializer,  # MỚI
    WorkerRegisterSerializer,
    WorkerProfileUpdateSerializer,
    AdminWorkerStatusUpdateSerializer,
)
from .models import PasswordResetOTP, WorkerProfile
from .tasks import send_otp_email
from .worker_profile import get_worker_profile_completeness
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
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'auth'
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

@CUSTOMER_REGISTER_SCHEMA
class CustomerRegisterView(generics.CreateAPIView):
    """
    POST /api/auth/register/
    API đăng ký tài khoản khách hàng.
    """
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'auth'
    permission_classes = [permissions.AllowAny]
    serializer_class = CustomerRegisterSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        data = build_token_response(user)

        return Response({
            "message": "Đăng ký tài khoản khách hàng thành công.",
            "data": data
        }, status=status.HTTP_201_CREATED)


#========================================================================================================================
@WORKER_REGISTER_SCHEMA
class WorkerRegisterView(generics.CreateAPIView):
    """
    POST /api/auth/worker/register/
    API đăng ký tài khoản nhân viên với trạng thái hồ sơ PENDING.
    """
    permission_classes = [permissions.AllowAny]
    serializer_class = WorkerRegisterSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        data = build_token_response(user)
        data["worker_profile"] = {
            "id": user.worker_profile.id,
            "status": user.worker_profile.status,
        }

        return Response({
            "message": "Tạo tài khoản nhân viên thành công.",
            "data": data
        }, status=status.HTTP_201_CREATED)


#========================================================================================================================
@WORKER_PROFILE_SCHEMA
class WorkerProfileView(generics.GenericAPIView):
    """
    GET/PATCH /api/auth/worker/profile/
    API xem và cập nhật từng phần hồ sơ nhân viên đang đăng nhập.
    """
    permission_classes = [IsWorkerRole]
    serializer_class = WorkerProfileUpdateSerializer
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get_object(self):
        return (
            WorkerProfile.objects
            .select_related('user', 'approved_by', 'registered_service')
            .prefetch_related('user__verification_documents', 'user__working_areas')
            .get(user=self.request.user)
        )

    def get(self, request, *args, **kwargs):
        return Response({
            'message': 'Lấy hồ sơ nhân viên thành công.',
            'data': self.get_serializer(self.get_object()).data,
        }, status=status.HTTP_200_OK)

    def patch(self, request, *args, **kwargs):
        serializer = self.get_serializer(
            self.get_object(),
            data=request.data,
            partial=True,
        )
        serializer.is_valid(raise_exception=True)
        profile = serializer.save()
        response_serializer = self.get_serializer(profile)

        return Response({
            "message": "Cập nhật hồ sơ nhân viên thành công.",
            "data": response_serializer.data,
        }, status=status.HTTP_200_OK)


#========================================================================================================================
@WORKER_PROFILE_SUBMIT_SCHEMA
class WorkerProfileSubmitView(generics.GenericAPIView):
    """POST /api/auth/worker/profile/submit/"""

    permission_classes = [IsWorkerRole]
    serializer_class = WorkerProfileUpdateSerializer

    @transaction.atomic
    def post(self, request, *args, **kwargs):
        profile = (
            WorkerProfile.objects
            .select_for_update(of=('self',))
            .select_related('user', 'approved_by', 'registered_service')
            .prefetch_related('user__verification_documents', 'user__working_areas')
            .get(user=request.user)
        )
        if profile.status != WorkerProfile.Status.DRAFT:
            raise ValidationError({
                'status': 'Chỉ hồ sơ ở trạng thái DRAFT mới có thể gửi duyệt.',
            })

        completeness = get_worker_profile_completeness(profile)
        if not completeness['is_complete']:
            raise ValidationError({
                'missing_fields': completeness['missing_fields'],
                'completion_percent': completeness['completion_percent'],
            })

        profile.status = WorkerProfile.Status.PENDING
        profile.rejection_reason = None
        profile.save(update_fields=['status', 'rejection_reason', 'updated_at'])

        return Response({
            'message': 'Gửi hồ sơ chờ duyệt thành công.',
            'data': self.get_serializer(profile).data,
        }, status=status.HTTP_200_OK)


#========================================================================================================================
@ADMIN_WORKER_PROFILE_LIST_SCHEMA
class AdminWorkerProfileListView(generics.ListAPIView):
    """GET /api/auth/admin/worker-profiles/?status=PENDING|ACTIVE|...|ALL"""

    permission_classes = [IsAdminRole]
    serializer_class = WorkerProfileUpdateSerializer

    def get_queryset(self):
        requested_status = self.request.query_params.get("status", "ALL").upper()
        queryset = (
            WorkerProfile.objects
            .select_related("user", "approved_by", "registered_service")
            .prefetch_related("user__verification_documents")
            .order_by("-created_at")
        )
        if requested_status == "ALL":
            return queryset
        if requested_status not in WorkerProfile.Status.values:
            raise ValidationError({"status": "Trạng thái không hợp lệ."})
        return queryset.filter(status=requested_status)


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
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'auth'
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
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'otp'
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

            transaction.on_commit(lambda: send_otp_email.delay(
                user.email,
                "Khôi phục mật khẩu CleanWise",
                text_message,
                html_message,
            ))

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
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'otp'
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
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'otp'
    permission_classes = [permissions.AllowAny]
    serializer_class = ResetPasswordSerializer

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()

        return Response({
            "message": "Đặt lại mật khẩu thành công."
        }, status=status.HTTP_200_OK)


#========================================================================================================================
# MỚI
@extend_schema(
    tags=["Auth - Password Reset"],
    summary="Đổi mật khẩu (đã đăng nhập)",
    request=ChangePasswordSerializer,
    responses={200: OpenApiTypes.OBJECT},
)
class ChangePasswordView(generics.GenericAPIView):
    """
    POST /api/auth/change-password/
    API đổi mật khẩu cho người dùng đang đăng nhập (cần mật khẩu cũ).
    """
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'auth'
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = ChangePasswordSerializer

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()

        return Response({
            "message": "Đổi mật khẩu thành công."
        }, status=status.HTTP_200_OK)


def _extract_jti_unverified(raw_token):
    """
    Giải mã payload để LẤY jti, KHÔNG dùng để tin tưởng nội dung token
    (chưa verify chữ ký ở bước này). Chỉ dùng jti để biết cần khóa dòng
    OutstandingToken nào trước khi cho simplejwt verify/rotate thật sự.
    Token giả mạo/sai định dạng sẽ bị chính simplejwt bắt lỗi ở bước
    is_valid() ngay sau, không lọt qua được.
    """
    try:
        payload = pyjwt.decode(raw_token, options={'verify_signature': False})
        return payload.get('jti')
    except Exception:
        return None


class CustomTokenRefreshView(TokenRefreshView):
    """
    Thay thế TokenRefreshView mặc định của simplejwt.

    Vấn đề gốc: với ROTATE_REFRESH_TOKENS=True + BLACKLIST_AFTER_ROTATION=True,
    bước "check token đã bị blacklist chưa" và bước "ghi blacklist token cũ"
    không nằm trong 1 khối có lock -> 2 request refresh cùng lúc với CÙNG
    1 refresh token có thể cùng pass check trước khi cái đầu tiên kịp ghi
    blacklist, dẫn tới cả 2 cùng tạo được token mới hợp lệ (rotation không
    còn đảm bảo "1 lần dùng").

    Cách vá: khóa (select_for_update) đúng dòng OutstandingToken tương ứng
    với jti của token TRƯỚC khi cho simplejwt verify/rotate. Request thứ 2
    phải chờ request thứ 1 commit xong (đã ghi blacklist) mới được đọc tiếp
    -> lúc đó check_blacklist() của simplejwt sẽ thấy token đã bị chặn và
    raise lỗi đúng như mong đợi.
    """
    permission_classes = [permissions.AllowAny]
    authentication_classes = []

    @transaction.atomic
    def post(self, request, *args, **kwargs):
        raw_token = request.data.get('refresh')

        if raw_token:
            jti = _extract_jti_unverified(raw_token)
            if jti:
                # Khóa dòng OutstandingToken nếu tồn tại. Token không tồn
                # tại trong bảng này (case hiếm, thiếu OUTSTANDING record)
                # thì bỏ qua lock, để simplejwt tự xử lý báo lỗi bình thường.
                OutstandingToken.objects.select_for_update().filter(jti=jti).first()

        serializer = TokenRefreshSerializer(data=request.data)
        try:
            serializer.is_valid(raise_exception=True)
        except TokenError as e:
            raise InvalidToken(e.args[0])

        return Response(serializer.validated_data, status=status.HTTP_200_OK)
    

class LogoutView(APIView):
    """POST /api/auth/logout/
    body: {"refresh": "...", "push_token": "..." (tùy chọn)}
    """
    permission_classes = [permissions.AllowAny]
    authentication_classes = []

    def post(self, request):
        raw = request.data.get("refresh")
        push_token = request.data.get("push_token")
        user_id = None

        if raw:
            try:
                token = RefreshToken(raw)
                user_id = token.get("user_id")
                token.blacklist()
            except TokenError:
                pass  # hết hạn hoặc đã bị blacklist: coi như đã logout

        # Chỉ xóa push token khi khớp đúng user sở hữu refresh token,
        # tránh người lạ biết push token là xóa được của người khác
        if push_token and user_id:
            DeviceToken.objects.filter(
                token=push_token, user_id=user_id
            ).delete()

        return Response({"message": "Đăng xuất thành công."}, status=status.HTTP_200_OK)