from django.conf import settings
from django.contrib.auth.tokens import default_token_generator
from django.core.files.storage import default_storage
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token as google_id_token
from rest_framework import serializers
from django.contrib.auth import get_user_model, authenticate
from django.contrib.auth.password_validation import validate_password
from django.utils.encoding import force_str
from django.utils.http import urlsafe_base64_decode
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema_field
from .models import CustomerProfile, WorkerProfile
from pathlib import Path
from uuid import uuid4

User = get_user_model()


@extend_schema_field(OpenApiTypes.URI)
class AvatarField(serializers.Field):
    """Field nhận file ảnh avatar khi ghi và trả về URL avatar khi đọc."""
    allowed_extensions = {".jpg", ".jpeg", ".png", ".webp"}
    allowed_content_types = {"image/jpeg", "image/png", "image/webp"}

    def to_representation(self, value):
        return value

    def to_internal_value(self, data):
        if data in ("", None):
            return None

        if not hasattr(data, "read"):
            raise serializers.ValidationError("Avatar phải là file hình ảnh.")

        extension = Path(data.name).suffix.lower()
        if extension not in self.allowed_extensions:
            raise serializers.ValidationError("Avatar chỉ hỗ trợ định dạng JPG, PNG hoặc WEBP.")

        content_type = getattr(data, "content_type", "")
        if content_type and content_type not in self.allowed_content_types:
            raise serializers.ValidationError("Avatar phải là file hình ảnh hợp lệ.")

        max_size = settings.CUSTOMER_AVATAR_MAX_SIZE
        if data.size > max_size:
            max_size_mb = max_size // (1024 * 1024)
            raise serializers.ValidationError(f"Avatar không được vượt quá {max_size_mb}MB.")

        return data


def save_customer_avatar(user, avatar_file):
    extension = Path(avatar_file.name).suffix.lower()
    filename = f"avatar_{uuid4().hex}{extension}"
    upload_path = f"{settings.CUSTOMER_AVATAR_UPLOAD_DIR}/user_{user.id}/{filename}"
    saved_path = default_storage.save(upload_path, avatar_file)
    return default_storage.url(saved_path)


class UserSerializer(serializers.ModelSerializer):
    """
    Serializer đại diện thông tin hiển thị của User.
    """
    class Meta:
        model = User
        fields = [
            'id',
            'username',
            'email',
            'first_name',
            'last_name',
            'role',
            'phone_number',
            'is_active',
            'date_joined'
        ]
        read_only_fields = ['id', 'date_joined']


class CustomerProfileSerializer(serializers.Serializer):
    """Serializer hiển thị và cập nhật hồ sơ khách hàng."""
    id = serializers.IntegerField(read_only=True)
    username = serializers.CharField(read_only=True)
    email = serializers.EmailField(required=False)
    first_name = serializers.CharField(required=False, allow_blank=True, max_length=150)
    last_name = serializers.CharField(required=False, allow_blank=True, max_length=150)
    phone_number = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True,
        max_length=15
    )
    role = serializers.CharField(read_only=True)
    gender = serializers.ChoiceField(
        choices=CustomerProfile.Gender.choices,
        required=False,
        allow_blank=True,
        allow_null=True
    )
    birth_date = serializers.DateField(required=False, allow_null=True)
    avatar = AvatarField(
        required=False,
        allow_null=True,
    )
    date_joined = serializers.DateTimeField(read_only=True)

    def to_representation(self, instance):
        profile = getattr(instance, "customer_profile", None)
        return {
            "id": instance.id,
            "username": instance.username,
            "email": instance.email,
            "first_name": instance.first_name,
            "last_name": instance.last_name,
            "phone_number": instance.phone_number,
            "role": instance.role,
            "gender": profile.gender if profile else None,
            "birth_date": profile.birth_date if profile else None,
            "avatar": profile.avatar if profile else None,
            "date_joined": instance.date_joined,
        }

    def validate_email(self, value):
        user = self.context["request"].user
        value = value.strip().lower()
        if User.objects.filter(email__iexact=value).exclude(pk=user.pk).exists():
            raise serializers.ValidationError("Email này đã được sử dụng.")
        return value

    def validate_phone_number(self, value):
        if value == "":
            return None

        user = self.context["request"].user
        if value and User.objects.filter(phone_number=value).exclude(pk=user.pk).exists():
            raise serializers.ValidationError("Số điện thoại này đã được sử dụng.")
        return value

    def update(self, instance, validated_data):
        profile_fields = ("gender", "birth_date", "avatar")
        user_fields = ("email", "first_name", "last_name", "phone_number")

        user_update_fields = []
        for field in user_fields:
            if field in validated_data:
                setattr(instance, field, validated_data[field])
                user_update_fields.append(field)

        if user_update_fields:
            instance.save(update_fields=user_update_fields + ["updated_at"])

        profile, _ = CustomerProfile.objects.get_or_create(user=instance)
        profile_update_fields = []
        for field in profile_fields:
            if field in validated_data:
                value = validated_data[field]
                if field == "avatar" and value:
                    value = save_customer_avatar(instance, value)
                setattr(profile, field, value)
                profile_update_fields.append(field)

        if profile_update_fields:
            profile.save(update_fields=profile_update_fields + ["updated_at"])

        instance._state.fields_cache["customer_profile"] = profile
        return instance


class GoogleLoginSerializer(serializers.Serializer):
    """Serializer nhận Google ID token từ frontend và xác thực với Google."""
    id_token = serializers.CharField(required=True, write_only=True)

    def validate(self, attrs):
        if not settings.GOOGLE_CLIENT_ID:
            raise serializers.ValidationError({
                "google": "Backend chưa cấu hình GOOGLE_CLIENT_ID."
            })

        try:
            payload = google_id_token.verify_oauth2_token(
                attrs["id_token"],
                google_requests.Request(),
                settings.GOOGLE_CLIENT_ID,
                clock_skew_in_seconds=7,
            )
        except ValueError:
            raise serializers.ValidationError({
                "id_token": "Google ID token không hợp lệ."
            })

        email = payload.get("email")
        email_verified = payload.get("email_verified")

        if not email:
            raise serializers.ValidationError({
                "email": "Google token không chứa email."
            })

        if not email_verified:
            raise serializers.ValidationError({
                "email": "Email Google chưa được xác minh."
            })

        first_name = payload.get("given_name") or ""
        last_name = payload.get("family_name") or ""
        picture = payload.get("picture")

        user = User.objects.filter(email__iexact=email).first()
        created = False

        if not user:
            user = User.objects.create(
                username=email,
                email=email,
                first_name=first_name,
                last_name=last_name,
                role=User.Role.CUSTOMER,
            )
            user.set_unusable_password()
            user.save(update_fields=["password"])
            CustomerProfile.objects.create(user=user, avatar=picture)
            created = True
        else:
            if not user.is_active:
                raise serializers.ValidationError("Tài khoản của bạn đã bị khóa.")

            changed_fields = []
            if first_name and not user.first_name:
                user.first_name = first_name
                changed_fields.append("first_name")
            if last_name and not user.last_name:
                user.last_name = last_name
                changed_fields.append("last_name")
            if changed_fields:
                user.save(update_fields=changed_fields)

            if user.role == User.Role.CUSTOMER and not hasattr(user, "customer_profile"):
                CustomerProfile.objects.create(user=user, avatar=picture)

        attrs["user"] = user
        attrs["created"] = created
        return attrs

class LoginSerializer(serializers.Serializer):
    """Serializer nhận dữ liệu đầu vào khi đăng nhập bằng số điện thoại hoặc username."""
    phone = serializers.CharField(required=False, write_only=True)
    username = serializers.CharField(required=False, write_only=True)
    password = serializers.CharField(required=True, write_only=True, style={'input_type': 'password'})

    def validate(self, attrs):
        phone = attrs.get('phone')
        username = attrs.get('username')
        password = attrs.get('password')

        if not phone and not username:
            raise serializers.ValidationError({
                "phone": "Vui lòng nhập số điện thoại hoặc username."
            })

        user = User.objects.filter(phone_number=phone).first() if phone else None
        auth_username = user.username if user else username

        user = authenticate(username=auth_username, password=password)
        if not user:
            raise serializers.ValidationError("Số điện thoại/username hoặc mật khẩu không chính xác.")
        
        if not user.is_active:
            raise serializers.ValidationError("Tài khoản của bạn đã bị khóa.")

        attrs['user'] = user
        return attrs

class RegisterSerializer(serializers.ModelSerializer):
    """
    Serializer nhận dữ liệu đầu vào khi đăng ký tài khoản mới.
    """
    password = serializers.CharField(
        required=True,
        write_only=True,
        style={'input_type': 'password'},
        validators=[validate_password]
    )
    password_confirm = serializers.CharField(
        required=True,
        write_only=True,
        style={'input_type': 'password'}
    )

    class Meta:
        model = User
        fields = [
            'username',
            'email',
            'password',
            'password_confirm',
            'first_name',
            'last_name',
            'role',
            'phone_number',
        ]
        extra_kwargs = {
            'email': {'required': True},
            'first_name': {'required': False},
            'last_name': {'required': False},
            'role': {'required': False},
            'phone_number': {'required': False},
        }

    def validate_email(self, value):
        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError("Email này đã được sử dụng.")
        return value

    def validate_phone_number(self, value):
        if value and User.objects.filter(phone_number=value).exists():
            raise serializers.ValidationError("Số điện thoại này đã được sử dụng.")
        return value

    def validate_role(self, value):
        if value == User.Role.ADMIN:
            raise serializers.ValidationError("Không thể đăng ký trực tiếp tài khoản quản trị viên.")
        return value

    def validate(self, attrs):
        if attrs['password'] != attrs['password_confirm']:
            raise serializers.ValidationError({
                "password_confirm": "Mật khẩu xác nhận không khớp."
            })
        return attrs

    def create(self, validated_data):
        validated_data.pop('password_confirm')
        password = validated_data.pop('password')
        user = User(**validated_data)
        user.set_password(password)
        user.save()

        if user.role == User.Role.WORKER:
            WorkerProfile.objects.create(user=user)
        else:
            CustomerProfile.objects.create(user=user)

        return user


class ForgotPasswordSerializer(serializers.Serializer):
    """Serializer nhận email để gửi hướng dẫn khôi phục mật khẩu."""
    email = serializers.EmailField(required=True)

    def validate_email(self, value):
        return value.strip().lower()

    def get_user(self):
        email = self.validated_data["email"]
        return User.objects.filter(email__iexact=email, is_active=True).first()


class ResetPasswordSerializer(serializers.Serializer):
    """Serializer kiểm tra token và đặt lại mật khẩu mới."""
    uid = serializers.CharField(required=True, write_only=True)
    token = serializers.CharField(required=True, write_only=True)
    new_password = serializers.CharField(
        required=True,
        write_only=True,
        style={'input_type': 'password'},
        validators=[validate_password]
    )
    new_password_confirm = serializers.CharField(
        required=True,
        write_only=True,
        style={'input_type': 'password'}
    )

    def validate(self, attrs):
        if attrs["new_password"] != attrs["new_password_confirm"]:
            raise serializers.ValidationError({
                "new_password_confirm": "Mật khẩu xác nhận không khớp."
            })

        try:
            user_id = force_str(urlsafe_base64_decode(attrs["uid"]))
            user = User.objects.get(pk=user_id, is_active=True)
        except (TypeError, ValueError, OverflowError, UnicodeDecodeError, User.DoesNotExist):
            raise serializers.ValidationError({
                "token": "Liên kết khôi phục mật khẩu không hợp lệ hoặc đã hết hạn."
            })

        if not default_token_generator.check_token(user, attrs["token"]):
            raise serializers.ValidationError({
                "token": "Liên kết khôi phục mật khẩu không hợp lệ hoặc đã hết hạn."
            })

        attrs["user"] = user
        return attrs

    def save(self, **kwargs):
        user = self.validated_data["user"]
        user.set_password(self.validated_data["new_password"])
        user.save(update_fields=["password"])
        return user


class TokenResponseSerializer(serializers.Serializer):
    """Serializer định nghĩa dữ liệu trả về sau khi đăng nhập thành công."""
    access = serializers.CharField()
    refresh = serializers.CharField()
    user = serializers.DictField()
    is_new_user = serializers.BooleanField(required=False)


