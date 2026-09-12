from django.conf import settings
from django.db import transaction
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token as google_id_token
from rest_framework import serializers
from django.contrib.auth import get_user_model, authenticate
from django.contrib.auth.password_validation import validate_password
from django.utils import timezone
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema_field
from apps.common.cloudinary_storage import upload_file, upload_image
from apps.common.encryption import encrypt_value
from .models import CustomerProfile, PasswordResetOTP, WorkerProfile, WorkerVerificationDocument
from .worker_profile import get_worker_profile_completeness
from pathlib import Path
import re

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


@extend_schema_field(OpenApiTypes.BINARY)
class WorkerImageUploadField(AvatarField):
    """File ảnh upload của nhân viên; OpenAPI hiển thị nút chọn file."""


def save_customer_avatar(user, avatar_file):
    folder = f"{settings.CLOUDINARY_CUSTOMER_AVATAR_FOLDER}/user_{user.id}"
    uploaded_image = upload_image(
        avatar_file,
        folder=folder,
        public_id_prefix="avatar",
        field_name="avatar",
    )
    return uploaded_image["url"]


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


class WorkerRegisterSerializer(RegisterSerializer):
    """Serializer đăng ký tài khoản dành riêng cho ứng dụng nhân viên."""

    class Meta(RegisterSerializer.Meta):
        fields = [
            'username',
            'email',
            'password',
            'password_confirm',
            'first_name',
            'last_name',
            'phone_number',
        ]
        extra_kwargs = {
            'email': {'required': True},
            'first_name': {'required': False},
            'last_name': {'required': False},
            'phone_number': {'required': False},
        }

    @transaction.atomic
    def create(self, validated_data):
        validated_data.pop('password_confirm')
        password = validated_data.pop('password')
        user = User(role=User.Role.WORKER, **validated_data)
        user.set_password(password)
        user.save()
        WorkerProfile.objects.create(
            user=user,
            status=WorkerProfile.Status.DRAFT,
        )
        return user


@extend_schema_field(OpenApiTypes.BINARY)
class WorkerDocumentField(serializers.FileField):
    """File xác minh nhân viên: ảnh, và tùy field có thể nhận PDF."""

    image_extensions = {".jpg", ".jpeg", ".png", ".webp"}
    image_content_types = {"image/jpeg", "image/png", "image/webp"}

    def __init__(self, *args, allow_pdf=False, **kwargs):
        self.allow_pdf = allow_pdf
        super().__init__(*args, **kwargs)

    def to_internal_value(self, data):
        data = super().to_internal_value(data)
        extension = Path(data.name).suffix.lower()
        allowed_extensions = set(self.image_extensions)
        allowed_content_types = set(self.image_content_types)
        if self.allow_pdf:
            allowed_extensions.add(".pdf")
            allowed_content_types.add("application/pdf")

        if extension not in allowed_extensions:
            message = "File chỉ hỗ trợ JPG, PNG hoặc WEBP."
            if self.allow_pdf:
                message = "File chỉ hỗ trợ JPG, PNG, WEBP hoặc PDF."
            raise serializers.ValidationError(message)

        content_type = getattr(data, "content_type", "")
        if content_type and content_type not in allowed_content_types:
            raise serializers.ValidationError("Định dạng file không hợp lệ.")

        if data.size > settings.WORKER_DOCUMENT_MAX_SIZE:
            max_size_mb = settings.WORKER_DOCUMENT_MAX_SIZE // (1024 * 1024)
            raise serializers.ValidationError(f"File không được vượt quá {max_size_mb}MB.")
        return data


class WorkerProfileUpdateSerializer(serializers.Serializer):
    """Cập nhật từng phần hồ sơ nhân viên và tự gửi duyệt khi đã đầy đủ."""

    ACTIVE_SENSITIVE_FIELDS = {
        "phone_number",
        "full_name",
        "gender",
        "birth_date",
        "portrait",
        "identity_number",
        "identity_issued_date",
        "identity_issued_place",
        "identity_front",
        "identity_back",
        "certificate_file",
        "certificate_number",
        "certificate_expiry_date",
        "bank_code",
        "bank_account_number",
        "bank_account_holder",
        "terms_accepted",
    }

    full_name = serializers.CharField(
        required=False,
        max_length=150,
        help_text="Họ và tên đầy đủ của nhân viên theo giấy tờ tùy thân.",
    )
    phone_number = serializers.CharField(
        required=False,
        max_length=15,
        help_text="Số điện thoại của nhân viên; phải là duy nhất trong hệ thống.",
    )
    gender = serializers.ChoiceField(
        required=False,
        choices=WorkerProfile.Gender.choices,
        help_text="Giới tính: MALE, FEMALE hoặc OTHER.",
    )
    birth_date = serializers.DateField(
        required=False,
        help_text="Ngày sinh theo định dạng YYYY-MM-DD; nhân viên phải đủ 18 tuổi.",
    )
    portrait = WorkerImageUploadField(
        required=False,
        write_only=True,
        help_text="Ảnh chân dung rõ mặt; hỗ trợ JPG, PNG, WEBP, tối đa 5 MB.",
    )
    identity_number = serializers.CharField(
        required=False,
        max_length=30,
        help_text="Số CCCD/CMND gồm 9 hoặc 12 chữ số và không được trùng.",
    )
    identity_issued_date = serializers.DateField(
        required=False,
        help_text="Ngày cấp CCCD/CMND theo định dạng YYYY-MM-DD; không được ở tương lai.",
    )
    identity_issued_place = serializers.CharField(
        required=False,
        max_length=255,
        help_text="Tên cơ quan hoặc nơi cấp CCCD/CMND.",
    )
    identity_front = WorkerDocumentField(
        required=False,
        write_only=True,
        help_text="Ảnh mặt trước CCCD/CMND. Bắt buộc gửi cùng identity_back trong một request.",
    )
    identity_back = WorkerDocumentField(
        required=False,
        write_only=True,
        help_text="Ảnh mặt sau CCCD/CMND. Bắt buộc gửi cùng identity_front trong một request.",
    )
    province = serializers.CharField(
        required=False,
        max_length=100,
        help_text="Tỉnh hoặc thành phố của địa chỉ hiện tại.",
    )
    ward = serializers.CharField(
        required=False,
        max_length=100,
        help_text="Phường hoặc xã của địa chỉ hiện tại.",
    )
    address_line = serializers.CharField(
        required=False,
        help_text="Số nhà, tên đường và thông tin địa chỉ chi tiết.",
    )
    latitude = serializers.DecimalField(
        required=False,
        allow_null=True,
        max_digits=10,
        decimal_places=7,
        help_text="Vĩ độ lấy từ vị trí hiện tại; không bắt buộc.",
    )
    longitude = serializers.DecimalField(
        required=False,
        allow_null=True,
        max_digits=10,
        decimal_places=7,
        help_text="Kinh độ lấy từ vị trí hiện tại; không bắt buộc.",
    )
    certificate_file = WorkerDocumentField(
        required=False,
        write_only=True,
        allow_pdf=True,
        help_text="Ảnh hoặc PDF chứng chỉ hành nghề; hỗ trợ JPG, PNG, WEBP, PDF, tối đa 10 MB.",
    )
    certificate_number = serializers.CharField(
        required=False,
        max_length=100,
        help_text="Số giấy phép hoặc số chứng chỉ hành nghề.",
    )
    certificate_expiry_date = serializers.DateField(
        required=False,
        help_text="Ngày hết hạn chứng chỉ theo định dạng YYYY-MM-DD; phải từ ngày hiện tại trở đi.",
    )
    bank_code = serializers.CharField(
        required=False,
        max_length=50,
        help_text="Mã ngân hàng, ví dụ VCB, TCB, MB.",
    )
    bank_account_number = serializers.CharField(
        required=False,
        write_only=True,
        max_length=30,
        help_text="Số tài khoản gồm 6–20 chữ số; được mã hóa trước khi lưu và không trả lại đầy đủ.",
    )
    bank_account_holder = serializers.CharField(
        required=False,
        max_length=150,
        help_text="Tên chủ tài khoản ngân hàng, nên viết in hoa và khớp thông tin ngân hàng.",
    )
    terms_accepted = serializers.BooleanField(
        required=False,
        write_only=True,
        help_text="Xác nhận đã đồng ý điều khoản; phải là true để hồ sơ được xem là đầy đủ.",
    )

    def validate_phone_number(self, value):
        value = value.strip()
        user = self.instance.user
        if User.objects.filter(phone_number=value).exclude(pk=user.pk).exists():
            raise serializers.ValidationError("Số điện thoại này đã được sử dụng.")
        return value

    def validate_identity_number(self, value):
        value = value.strip()
        if not re.fullmatch(r"(?:\d{9}|\d{12})", value):
            raise serializers.ValidationError("CCCD/CMND phải gồm 9 hoặc 12 chữ số.")
        if WorkerProfile.objects.filter(identity_number=value).exclude(pk=self.instance.pk).exists():
            raise serializers.ValidationError("Số CCCD/CMND này đã được sử dụng.")
        return value

    def validate_bank_account_number(self, value):
        value = value.strip()
        if not re.fullmatch(r"\d{6,20}", value):
            raise serializers.ValidationError("Số tài khoản phải gồm từ 6 đến 20 chữ số.")
        return value

    def validate(self, attrs):
        if self.instance.status not in {
            WorkerProfile.Status.DRAFT,
            WorkerProfile.Status.PENDING,
            WorkerProfile.Status.ACTIVE,
            WorkerProfile.Status.REJECTED,
        }:
            raise serializers.ValidationError({
                "status": "Hồ sơ đang bị tạm khóa và không thể cập nhật."
            })

        if self.instance.status == WorkerProfile.Status.ACTIVE:
            sensitive_fields = sorted(self.ACTIVE_SENSITIVE_FIELDS.intersection(attrs))
            if sensitive_fields:
                raise serializers.ValidationError({
                    "sensitive_fields": (
                        "Hồ sơ đã được duyệt. Không thể cập nhật các thông tin nhạy cảm: "
                        + ", ".join(sensitive_fields)
                        + "."
                    )
                })

        identity_front = attrs.get("identity_front")
        identity_back = attrs.get("identity_back")
        if bool(identity_front) != bool(identity_back):
            raise serializers.ValidationError({
                "identity_documents": (
                    "Phải gửi đồng thời ảnh mặt trước và mặt sau CCCD/CMND."
                )
            })

        today = timezone.localdate()
        birth_date = attrs.get("birth_date", self.instance.birth_date)
        if birth_date:
            age = today.year - birth_date.year - (
                (today.month, today.day) < (birth_date.month, birth_date.day)
            )
            if age < 18:
                raise serializers.ValidationError({
                    "birth_date": "Nhân viên phải đủ 18 tuổi."
                })

        issued_date = attrs.get("identity_issued_date", self.instance.identity_issued_date)
        if issued_date and issued_date > today:
            raise serializers.ValidationError({
                "identity_issued_date": "Ngày cấp giấy tờ không được ở tương lai."
            })

        expiry_date = attrs.get("certificate_expiry_date", self.instance.certificate_expiry_date)
        if expiry_date and expiry_date < today:
            raise serializers.ValidationError({
                "certificate_expiry_date": "Chứng chỉ đã hết hạn."
            })
        return attrs

    @staticmethod
    def _save_verification_document(user, document_type, uploaded_file, field_name):
        extension = Path(uploaded_file.name).suffix.lower()
        file_type = (
            WorkerVerificationDocument.FileType.PDF
            if extension == ".pdf"
            else WorkerVerificationDocument.FileType.IMAGE
        )
        uploaded = upload_file(
            uploaded_file,
            folder=f"{settings.CLOUDINARY_WORKER_PROFILE_FOLDER}/user_{user.id}",
            public_id_prefix=document_type.lower(),
            field_name=field_name,
            resource_type="auto" if file_type == WorkerVerificationDocument.FileType.PDF else "image",
        )
        document = user.verification_documents.filter(
            document_type=document_type
        ).order_by("-created_at").first()
        if document:
            document.file = uploaded["url"]
            document.file_type = file_type
            document.save(update_fields=["file", "file_type"])
        else:
            WorkerVerificationDocument.objects.create(
                worker=user,
                document_type=document_type,
                file=uploaded["url"],
                file_type=file_type,
            )

    @transaction.atomic
    def update(self, instance, validated_data):
        portrait = validated_data.pop("portrait", None)
        identity_front = validated_data.pop("identity_front", None)
        identity_back = validated_data.pop("identity_back", None)
        certificate_file = validated_data.pop("certificate_file", None)
        bank_account_number = validated_data.pop("bank_account_number", None)
        terms_accepted = validated_data.pop("terms_accepted", None)
        phone_number = validated_data.pop("phone_number", None)

        if phone_number is not None:
            instance.user.phone_number = phone_number
            instance.user.save(update_fields=["phone_number", "updated_at"])

        for field_name, value in validated_data.items():
            if isinstance(value, str):
                value = value.strip()
            setattr(instance, field_name, value)

        if portrait:
            uploaded = upload_image(
                portrait,
                folder=f"{settings.CLOUDINARY_WORKER_PROFILE_FOLDER}/user_{instance.user_id}",
                public_id_prefix="portrait",
                field_name="portrait",
            )
            instance.avatar = uploaded["url"]

        if bank_account_number:
            instance.bank_account_number_encrypted = encrypt_value(bank_account_number)
            instance.bank_account_last4 = bank_account_number[-4:]

        if terms_accepted and not instance.terms_accepted_at:
            instance.terms_accepted_at = timezone.now()

        instance.save()

        documents = (
            (identity_front, WorkerVerificationDocument.DocumentType.IDENTITY_FRONT, "identity_front"),
            (identity_back, WorkerVerificationDocument.DocumentType.IDENTITY_BACK, "identity_back"),
            (certificate_file, WorkerVerificationDocument.DocumentType.CERTIFICATE, "certificate_file"),
        )
        for uploaded_file, document_type, field_name in documents:
            if uploaded_file:
                self._save_verification_document(
                    instance.user,
                    document_type,
                    uploaded_file,
                    field_name,
                )

        completeness = get_worker_profile_completeness(instance)
        if completeness["is_complete"] and instance.status != WorkerProfile.Status.ACTIVE:
            instance.status = WorkerProfile.Status.PENDING
            instance.submitted_at = timezone.now()
            instance.rejection_reason = None
            instance.save(update_fields=[
                "status",
                "submitted_at",
                "rejection_reason",
                "updated_at",
            ])
        return instance

    def to_representation(self, instance):
        documents = {
            document.document_type: document.file
            for document in instance.user.verification_documents.order_by("created_at")
        }
        completeness = get_worker_profile_completeness(instance)
        return {
            "id": instance.id,
            "user_id": instance.user_id,
            "username": instance.user.username,
            "email": instance.user.email,
            "phone_number": instance.user.phone_number,
            "role": instance.user.role,
            "status": instance.status,
            "full_name": instance.full_name,
            "gender": instance.gender,
            "birth_date": instance.birth_date,
            "portrait": instance.avatar,
            "identity_number": instance.identity_number,
            "identity_issued_date": instance.identity_issued_date,
            "identity_issued_place": instance.identity_issued_place,
            "identity_front": documents.get(WorkerVerificationDocument.DocumentType.IDENTITY_FRONT),
            "identity_back": documents.get(WorkerVerificationDocument.DocumentType.IDENTITY_BACK),
            "province": instance.province,
            "ward": instance.ward,
            "address_line": instance.address_line,
            "latitude": instance.latitude,
            "longitude": instance.longitude,
            "certificate_file": documents.get(WorkerVerificationDocument.DocumentType.CERTIFICATE),
            "certificate_number": instance.certificate_number,
            "certificate_expiry_date": instance.certificate_expiry_date,
            "bank_code": instance.bank_code,
            "bank_account_number": (
                f"******{instance.bank_account_last4}"
                if instance.bank_account_last4
                else None
            ),
            "bank_account_holder": instance.bank_account_holder,
            "terms_accepted": instance.terms_accepted_at is not None,
            "submitted_at": instance.submitted_at,
            "approved_by": (
                UserSerializer(instance.approved_by).data
                if instance.approved_by
                else None
            ),
            "approved_at": instance.approved_at,
            "rejection_reason": instance.rejection_reason,
            "created_at": instance.created_at,
            "updated_at": instance.updated_at,
            **completeness,
        }


class AdminWorkerStatusUpdateSerializer(serializers.Serializer):
    """Admin cập nhật trạng thái xét duyệt của hồ sơ nhân viên."""

    status = serializers.ChoiceField(
        choices=WorkerProfile.Status.choices,
        help_text="Trạng thái mới: DRAFT, PENDING, ACTIVE, REJECTED hoặc SUSPENDED.",
    )
    reason = serializers.CharField(
        required=False,
        allow_blank=False,
        help_text="Lý do bắt buộc khi chuyển hồ sơ sang REJECTED; có thể dùng làm ghi chú khi SUSPENDED.",
    )

    def validate(self, attrs):
        target_status = attrs["status"]
        reason = attrs.get("reason")
        if target_status == WorkerProfile.Status.REJECTED and not reason:
            raise serializers.ValidationError({
                "reason": "Vui lòng nhập lý do từ chối hồ sơ."
            })

        if target_status in {
            WorkerProfile.Status.PENDING,
            WorkerProfile.Status.ACTIVE,
        }:
            completeness = get_worker_profile_completeness(self.instance)
            if not completeness["is_complete"]:
                raise serializers.ValidationError({
                    "status": "Không thể chuyển hồ sơ chưa đầy đủ sang trạng thái này.",
                    "missing_fields": completeness["missing_fields"],
                })
        return attrs

    @transaction.atomic
    def update(self, instance, validated_data):
        instance = WorkerProfile.objects.select_for_update().get(pk=instance.pk)
        target_status = validated_data["status"]
        reason = validated_data.get("reason")
        now = timezone.now()

        instance.status = target_status
        update_fields = ["status", "updated_at"]

        if target_status == WorkerProfile.Status.ACTIVE:
            instance.approved_by = self.context["request"].user
            instance.approved_at = now
            instance.rejection_reason = None
            update_fields.extend(["approved_by", "approved_at", "rejection_reason"])
        elif target_status == WorkerProfile.Status.REJECTED:
            instance.approved_by = None
            instance.approved_at = None
            instance.rejection_reason = reason
            update_fields.extend(["approved_by", "approved_at", "rejection_reason"])
        elif target_status == WorkerProfile.Status.PENDING:
            instance.approved_by = None
            instance.approved_at = None
            instance.rejection_reason = None
            instance.submitted_at = now
            update_fields.extend([
                "approved_by",
                "approved_at",
                "rejection_reason",
                "submitted_at",
            ])
        elif target_status == WorkerProfile.Status.DRAFT:
            instance.approved_by = None
            instance.approved_at = None
            instance.rejection_reason = None
            instance.submitted_at = None
            update_fields.extend([
                "approved_by",
                "approved_at",
                "rejection_reason",
                "submitted_at",
            ])
        elif target_status == WorkerProfile.Status.SUSPENDED and reason:
            instance.rejection_reason = reason
            update_fields.append("rejection_reason")

        instance.save(update_fields=update_fields)
        return instance


class ForgotPasswordSerializer(serializers.Serializer):
    """Serializer nhận email để gửi hướng dẫn khôi phục mật khẩu."""
    email = serializers.EmailField(required=True)

    def validate_email(self, value):
        return value.strip().lower()

    def get_user(self):
        email = self.validated_data["email"]
        return User.objects.filter(email__iexact=email, is_active=True).first()


class VerifyPasswordResetOTPSerializer(serializers.Serializer):
    """Serializer kiểm tra mã OTP trước khi cho phép nhập mật khẩu mới."""
    email = serializers.EmailField(required=True, write_only=True)
    code = serializers.RegexField(
        regex=r"^\d{6}$",
        required=True,
        write_only=True,
        error_messages={
            "invalid": "Mã xác thực phải gồm 6 chữ số."
        }
    )

    def validate_email(self, value):
        return value.strip().lower()

    def validate(self, attrs):
        user = User.objects.filter(email__iexact=attrs["email"], is_active=True).first()
        if not user:
            raise serializers.ValidationError({
                "code": "Mã xác thực không hợp lệ hoặc đã hết hạn."
            })

        otp = (
            PasswordResetOTP.objects
            .filter(user=user, used_at__isnull=True)
            .order_by("-created_at")
            .first()
        )

        if not otp or otp.is_expired or otp.attempts >= settings.PASSWORD_RESET_OTP_MAX_ATTEMPTS:
            raise serializers.ValidationError({
                "code": "Mã xác thực không hợp lệ hoặc đã hết hạn."
            })

        if not otp.check_code(attrs["code"]):
            otp.attempts += 1
            otp.save(update_fields=["attempts"])
            raise serializers.ValidationError({
                "code": "Mã xác thực không hợp lệ hoặc đã hết hạn."
            })

        attrs["otp"] = otp
        return attrs

    def save(self, **kwargs):
        otp = self.validated_data["otp"]
        if not otp.is_verified:
            otp.mark_verified()
        return otp


class ResetPasswordSerializer(serializers.Serializer):
    """Serializer kiểm tra mã OTP và đặt lại mật khẩu mới."""
    email = serializers.EmailField(required=True, write_only=True)
    code = serializers.RegexField(
        regex=r"^\d{6}$",
        required=True,
        write_only=True,
        error_messages={
            "invalid": "Mã xác thực phải gồm 6 chữ số."
        }
    )
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

    def validate_email(self, value):
        return value.strip().lower()

    def validate(self, attrs):
        if attrs["new_password"] != attrs["new_password_confirm"]:
            raise serializers.ValidationError({
                "new_password_confirm": "Mật khẩu xác nhận không khớp."
            })

        user = User.objects.filter(email__iexact=attrs["email"], is_active=True).first()
        if not user:
            raise serializers.ValidationError({
                "code": "Mã xác thực không hợp lệ hoặc đã hết hạn."
            })

        otp = (
            PasswordResetOTP.objects
            .filter(user=user, used_at__isnull=True)
            .order_by("-created_at")
            .first()
        )

        if (
            not otp
            or otp.is_expired
            or not otp.is_verified
            or otp.attempts >= settings.PASSWORD_RESET_OTP_MAX_ATTEMPTS
        ):
            raise serializers.ValidationError({
                "code": "Vui lòng xác minh mã OTP trước khi đặt lại mật khẩu."
            })

        if not otp.check_code(attrs["code"]):
            otp.attempts += 1
            otp.save(update_fields=["attempts"])
            raise serializers.ValidationError({
                "code": "Mã xác thực không hợp lệ hoặc đã hết hạn."
            })

        attrs["user"] = user
        attrs["otp"] = otp
        return attrs

    def save(self, **kwargs):
        user = self.validated_data["user"]
        user.set_password(self.validated_data["new_password"])
        user.save(update_fields=["password"])
        self.validated_data["otp"].mark_used()
        return user


class TokenResponseSerializer(serializers.Serializer):
    """Serializer định nghĩa dữ liệu trả về sau khi đăng nhập thành công."""
    access = serializers.CharField()
    refresh = serializers.CharField()
    user = serializers.DictField()
    is_new_user = serializers.BooleanField(required=False)


class WorkerRegisterResponseSerializer(TokenResponseSerializer):
    """Dữ liệu JWT và trạng thái hồ sơ sau khi đăng ký nhân viên."""
    profile_status = serializers.ChoiceField(choices=WorkerProfile.Status.choices)


