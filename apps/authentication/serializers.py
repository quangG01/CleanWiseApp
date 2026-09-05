from django.conf import settings
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token as google_id_token
from rest_framework import serializers
from django.contrib.auth import get_user_model, authenticate
from django.contrib.auth.password_validation import validate_password
from .models import CustomerProfile, WorkerProfile

User = get_user_model()


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
    """Serializer nhận dữ liệu đầu vào khi Đăng nhập."""
    username = serializers.CharField(required=True, write_only=True)
    password = serializers.CharField(required=True, write_only=True, style={'input_type': 'password'})

    def validate(self, attrs):
        username = attrs.get('username')
        password = attrs.get('password')

        user = authenticate(username=username, password=password)
        if not user:
            raise serializers.ValidationError("Tên đăng nhập hoặc mật khẩu không chính xác.")
        
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


class TokenResponseSerializer(serializers.Serializer):
    """Serializer định nghĩa dữ liệu trả về sau khi đăng nhập thành công."""
    access = serializers.CharField()
    refresh = serializers.CharField()
    user = serializers.DictField()
    is_new_user = serializers.BooleanField(required=False)
