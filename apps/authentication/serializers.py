import re
from pathlib import Path

from django.conf import settings
from django.contrib.auth import authenticate, get_user_model
from django.contrib.auth.password_validation import validate_password
from django.db import transaction
from django.utils import timezone
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema_field
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token as google_id_token
from rest_framework import serializers

from apps.common.cloudinary_storage import upload_file, upload_image
from apps.services.models import Service
from .models import PasswordResetOTP, WorkerProfile, WorkerVerificationDocument
from .worker_profile import get_worker_profile_completeness

User = get_user_model()


@extend_schema_field(OpenApiTypes.URI)
class AvatarField(serializers.Field):
    allowed_extensions = {'.jpg', '.jpeg', '.png', '.webp'}
    allowed_content_types = {'image/jpeg', 'image/png', 'image/webp'}

    def to_representation(self, value):
        return value

    def to_internal_value(self, data):
        if data in ('', None):
            return None
        if not hasattr(data, 'read'):
            raise serializers.ValidationError('Avatar phải là file hình ảnh.')
        extension = Path(data.name).suffix.lower()
        if extension not in self.allowed_extensions:
            raise serializers.ValidationError('Avatar chỉ hỗ trợ định dạng JPG, PNG hoặc WEBP.')
        content_type = getattr(data, 'content_type', '')
        if content_type and content_type not in self.allowed_content_types:
            raise serializers.ValidationError('Avatar phải là file hình ảnh hợp lệ.')
        if data.size > settings.CUSTOMER_AVATAR_MAX_SIZE:
            max_size_mb = settings.CUSTOMER_AVATAR_MAX_SIZE // (1024 * 1024)
            raise serializers.ValidationError(f'Avatar không được vượt quá {max_size_mb}MB.')
        return data


@extend_schema_field(OpenApiTypes.BINARY)
class WorkerImageUploadField(AvatarField):
    pass


def save_customer_avatar(user, avatar_file):
    uploaded = upload_image(
        avatar_file,
        folder=f'{settings.CLOUDINARY_CUSTOMER_AVATAR_FOLDER}/user_{user.id}',
        public_id_prefix='avatar',
        field_name='avatar',
    )
    return uploaded['url']


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = [
            'id', 'username', 'email', 'phone_number', 'first_name', 'last_name',
            'gender', 'birth_date', 'avatar', 'role', 'is_active', 'date_joined',
        ]
        read_only_fields = ['id', 'date_joined']


class CustomerProfileSerializer(serializers.Serializer):
    id = serializers.IntegerField(read_only=True)
    username = serializers.CharField(read_only=True)
    email = serializers.EmailField(required=False)
    first_name = serializers.CharField(required=False, allow_blank=True, max_length=150)
    last_name = serializers.CharField(required=False, allow_blank=True, max_length=150)
    phone_number = serializers.CharField(required=False, allow_blank=True, allow_null=True, max_length=15)
    role = serializers.CharField(read_only=True)
    gender = serializers.ChoiceField(
        choices=User.Gender.choices,
        required=False,
        allow_blank=True,
        allow_null=True,
    )
    birth_date = serializers.DateField(required=False, allow_null=True)
    avatar = AvatarField(required=False, allow_null=True)
    date_joined = serializers.DateTimeField(read_only=True)

    def to_representation(self, instance):
        return {
            'id': instance.id,
            'username': instance.username,
            'email': instance.email,
            'first_name': instance.first_name,
            'last_name': instance.last_name,
            'phone_number': instance.phone_number,
            'role': instance.role,
            'gender': instance.gender,
            'birth_date': instance.birth_date,
            'avatar': instance.avatar,
            'date_joined': instance.date_joined,
        }

    def validate_email(self, value):
        value = value.strip().lower()
        if User.objects.filter(email__iexact=value).exclude(pk=self.instance.pk).exists():
            raise serializers.ValidationError('Email này đã được sử dụng.')
        return value

    def validate_phone_number(self, value):
        if value == '':
            return None
        if value and User.objects.filter(phone_number=value).exclude(pk=self.instance.pk).exists():
            raise serializers.ValidationError('Số điện thoại này đã được sử dụng.')
        return value

    def update(self, instance, validated_data):
        for field, value in validated_data.items():
            if field == 'avatar' and value:
                value = save_customer_avatar(instance, value)
            setattr(instance, field, value)
        if validated_data:
            instance.save()
        return instance


class GoogleLoginSerializer(serializers.Serializer):
    id_token = serializers.CharField(required=True, write_only=True)

    def validate(self, attrs):
        if not settings.GOOGLE_CLIENT_ID:
            raise serializers.ValidationError({'google': 'Backend chưa cấu hình GOOGLE_CLIENT_ID.'})
        try:
            payload = google_id_token.verify_oauth2_token(
                attrs['id_token'],
                google_requests.Request(),
                settings.GOOGLE_CLIENT_ID,
                clock_skew_in_seconds=7,
            )
        except ValueError:
            raise serializers.ValidationError({'id_token': 'Google ID token không hợp lệ.'})

        email = payload.get('email')
        if not email:
            raise serializers.ValidationError({'email': 'Google token không chứa email.'})
        if not payload.get('email_verified'):
            raise serializers.ValidationError({'email': 'Email Google chưa được xác minh.'})

        user = User.objects.filter(email__iexact=email).first()
        created = False
        if not user:
            user = User.objects.create(
                username=email,
                email=email,
                first_name=payload.get('given_name') or '',
                last_name=payload.get('family_name') or '',
                avatar=payload.get('picture'),
                role=User.Role.CUSTOMER,
            )
            user.set_unusable_password()
            user.save(update_fields=['password'])
            created = True
        elif not user.is_active:
            raise serializers.ValidationError('Tài khoản của bạn đã bị khóa.')

        attrs['user'] = user
        attrs['created'] = created
        return attrs


class LoginSerializer(serializers.Serializer):
    phone = serializers.CharField(required=False, write_only=True)
    username = serializers.CharField(required=False, write_only=True)
    password = serializers.CharField(required=True, write_only=True, style={'input_type': 'password'})

    def validate(self, attrs):
        phone = attrs.get('phone')
        username = attrs.get('username')
        if not phone and not username:
            raise serializers.ValidationError({'phone': 'Vui lòng nhập số điện thoại hoặc username.'})
        matched_user = User.objects.filter(phone_number=phone).first() if phone else None
        auth_username = matched_user.username if matched_user else username
        user = authenticate(username=auth_username, password=attrs['password'])
        if not user:
            raise serializers.ValidationError('Số điện thoại/username hoặc mật khẩu không chính xác.')
        if not user.is_active:
            raise serializers.ValidationError('Tài khoản của bạn đã bị khóa.')
        attrs['user'] = user
        return attrs


class CustomerRegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(
        required=True,
        write_only=True,
        style={'input_type': 'password'},
        validators=[validate_password],
    )
    password_confirm = serializers.CharField(required=True, write_only=True, style={'input_type': 'password'})

    class Meta:
        model = User
        fields = [
            'username', 'email', 'password', 'password_confirm', 'first_name',
            'last_name', 'gender', 'birth_date', 'phone_number',
        ]
        extra_kwargs = {
            'email': {'required': True},
            'first_name': {'required': False},
            'last_name': {'required': False},
            'gender': {'required': False},
            'birth_date': {'required': False},
            'phone_number': {'required': False},
        }

    def validate_username(self, value):
        value = value.strip()
        if User.objects.filter(username__iexact=value).exists():
            raise serializers.ValidationError('Tên đăng nhập này đã được sử dụng.')
        return value

    def validate_email(self, value):
        value = value.strip().lower()
        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError('Email này đã được sử dụng.')
        return value

    def validate_phone_number(self, value):
        if value in ('', None):
            return None
        value = value.strip()
        if not re.fullmatch(r'(?:\+84|0)\d{9}', value):
            raise serializers.ValidationError('Số điện thoại Việt Nam không hợp lệ.')
        if User.objects.filter(phone_number=value).exists():
            raise serializers.ValidationError('Số điện thoại này đã được sử dụng.')
        return value

    def validate_birth_date(self, value):
        if value and value > timezone.localdate():
            raise serializers.ValidationError('Ngày sinh không được ở tương lai.')
        return value

    def validate(self, attrs):
        if 'role' in self.initial_data:
            raise serializers.ValidationError({
                'role': 'Role của API đăng ký khách hàng được backend cố định là CUSTOMER.',
            })
        if attrs['password'] != attrs['password_confirm']:
            raise serializers.ValidationError({'password_confirm': 'Mật khẩu xác nhận không khớp.'})
        return attrs

    @transaction.atomic
    def create(self, validated_data):
        validated_data.pop('password_confirm')
        password = validated_data.pop('password')
        user = User(role=User.Role.CUSTOMER, **validated_data)
        user.set_password(password)
        user.save()
        return user


class WorkerRegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(
        required=True,
        write_only=True,
        style={'input_type': 'password'},
        validators=[validate_password],
    )
    password_confirm = serializers.CharField(required=True, write_only=True, style={'input_type': 'password'})

    class Meta:
        model = User
        fields = [
            'username', 'email', 'password', 'password_confirm',
            'first_name', 'last_name', 'gender', 'birth_date', 'phone_number',
        ]
        extra_kwargs = {
            'email': {'required': True},
            'first_name': {'required': True, 'allow_blank': False},
            'last_name': {'required': True, 'allow_blank': False},
            'gender': {'required': True, 'allow_null': False, 'allow_blank': False},
            'birth_date': {'required': True, 'allow_null': False},
            'phone_number': {'required': True, 'allow_null': False, 'allow_blank': False},
        }

    def validate_username(self, value):
        value = value.strip()
        if User.objects.filter(username__iexact=value).exists():
            raise serializers.ValidationError('Tên đăng nhập này đã được sử dụng.')
        return value

    def validate_email(self, value):
        value = value.strip().lower()
        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError('Email này đã được sử dụng.')
        return value

    def validate_phone_number(self, value):
        value = value.strip()
        if not re.fullmatch(r'(?:\+84|0)\d{9}', value):
            raise serializers.ValidationError('Số điện thoại Việt Nam không hợp lệ.')
        if User.objects.filter(phone_number=value).exists():
            raise serializers.ValidationError('Số điện thoại này đã được sử dụng.')
        return value

    def validate_birth_date(self, value):
        today = timezone.localdate()
        if value > today:
            raise serializers.ValidationError('Ngày sinh không được ở tương lai.')
        age = today.year - value.year - ((today.month, today.day) < (value.month, value.day))
        if age < 18:
            raise serializers.ValidationError('Nhân viên phải đủ 18 tuổi.')
        return value

    def validate(self, attrs):
        if 'role' in self.initial_data:
            raise serializers.ValidationError({
                'role': 'Role của API đăng ký nhân viên được backend cố định là WORKER.',
            })
        if attrs['password'] != attrs['password_confirm']:
            raise serializers.ValidationError({'password_confirm': 'Mật khẩu xác nhận không khớp.'})
        return attrs

    @transaction.atomic
    def create(self, validated_data):
        validated_data.pop('password_confirm')
        password = validated_data.pop('password')
        user = User(role=User.Role.WORKER, **validated_data)
        user.set_password(password)
        user.save()
        WorkerProfile.objects.create(user=user)
        return user


@extend_schema_field(OpenApiTypes.BINARY)
class WorkerDocumentField(serializers.FileField):
    image_extensions = {'.jpg', '.jpeg', '.png', '.webp'}
    image_content_types = {'image/jpeg', 'image/png', 'image/webp'}

    def __init__(self, *args, allow_pdf=False, **kwargs):
        self.allow_pdf = allow_pdf
        super().__init__(*args, **kwargs)

    def to_internal_value(self, data):
        data = super().to_internal_value(data)
        extensions = set(self.image_extensions)
        content_types = set(self.image_content_types)
        if self.allow_pdf:
            extensions.add('.pdf')
            content_types.add('application/pdf')
        if Path(data.name).suffix.lower() not in extensions:
            raise serializers.ValidationError('Định dạng file không được hỗ trợ.')
        content_type = getattr(data, 'content_type', '')
        if content_type and content_type not in content_types:
            raise serializers.ValidationError('Định dạng file không hợp lệ.')
        if data.size > settings.WORKER_DOCUMENT_MAX_SIZE:
            max_size_mb = settings.WORKER_DOCUMENT_MAX_SIZE // (1024 * 1024)
            raise serializers.ValidationError(f'File không được vượt quá {max_size_mb}MB.')
        return data


class WorkerRegisteredServiceSerializer(serializers.ModelSerializer):
    id = serializers.IntegerField(read_only=True, help_text='ID dịch vụ, dùng làm service_id khi cập nhật hồ sơ.')
    code = serializers.CharField(read_only=True, help_text='Mã định danh duy nhất của dịch vụ.')
    section_code = serializers.CharField(read_only=True, help_text='Mã nhóm chứa dịch vụ.')
    name = serializers.CharField(read_only=True, help_text='Tên dịch vụ hiển thị cho người dùng.')

    class Meta:
        model = Service
        fields = ['id', 'code', 'section_code', 'name']


# Các field mà admin được phép đánh dấu là "sai, cần sửa lại" — khớp với
# field thật sự nhân viên nhập trong luồng profile-setup.
REJECTABLE_PROFILE_FIELDS = {
    'first_name', 'last_name', 'phone_number', 'gender', 'birth_date',
    'bio', 'experience_years', 'identity_number', 'service_id',
    'portrait', 'identity_front', 'identity_back', 'certificate_file',
}


class WorkerProfileUpdateSerializer(serializers.Serializer):
    id = serializers.IntegerField(read_only=True, help_text='ID hồ sơ nhân viên.')
    user_id = serializers.IntegerField(read_only=True, help_text='ID tài khoản sở hữu hồ sơ.')
    username = serializers.CharField(read_only=True, help_text='Tên đăng nhập, không thể sửa tại API này.')
    email = serializers.EmailField(read_only=True, help_text='Email tài khoản, không thể sửa tại API này.')
    first_name = serializers.CharField(required=False, allow_blank=True, max_length=150, help_text='Tên của nhân viên.')
    last_name = serializers.CharField(required=False, allow_blank=True, max_length=150, help_text='Họ và tên đệm của nhân viên.')
    phone_number = serializers.CharField(required=False, allow_blank=True, allow_null=True, max_length=15, help_text='Số điện thoại duy nhất của nhân viên.')
    gender = serializers.ChoiceField(
        choices=User.Gender.choices,
        required=False,
        allow_blank=True,
        allow_null=True,
        help_text='Giới tính: MALE, FEMALE hoặc OTHER.',
    )
    birth_date = serializers.DateField(required=False, allow_null=True, help_text='Ngày sinh; nhân viên phải đủ 18 tuổi.')
    role = serializers.CharField(read_only=True, help_text='Vai trò tài khoản, luôn là WORKER đối với API này.')
    status = serializers.ChoiceField(choices=WorkerProfile.Status.choices, read_only=True, help_text='Trạng thái xét duyệt hồ sơ; nhân viên không thể tự sửa.')
    bio = serializers.CharField(required=False, allow_blank=True, allow_null=True, help_text='Giới thiệu hoặc mô tả kinh nghiệm của nhân viên.')
    experience_years = serializers.IntegerField(required=False, min_value=0, help_text='Số năm kinh nghiệm, không được âm.')
    identity_number = serializers.CharField(required=False, allow_blank=True, allow_null=True, max_length=30, help_text='Số CCCD/CMND gồm 9 hoặc 12 chữ số và không được trùng.')
    registered_service = WorkerRegisteredServiceSerializer(read_only=True, help_text='Thông tin loại dịch vụ nhân viên đã đăng ký.')
    service_id = serializers.PrimaryKeyRelatedField(
        source='registered_service',
        queryset=Service.objects.filter(is_active=True),
        required=False,
        allow_null=True,
        write_only=True,
        help_text='ID dịch vụ đang hoạt động muốn đăng ký; gửi null để bỏ lựa chọn.',
    )
    portrait = WorkerImageUploadField(required=False, allow_null=True, help_text='Ảnh chân dung JPG, JPEG, PNG hoặc WEBP.')
    identity_front = WorkerDocumentField(required=False, help_text='Ảnh mặt trước CCCD/CMND; phải gửi cùng identity_back.')
    identity_back = WorkerDocumentField(required=False, help_text='Ảnh mặt sau CCCD/CMND; phải gửi cùng identity_front.')
    certificate_file = WorkerDocumentField(required=False, allow_pdf=True, help_text='Chứng chỉ nghề nghiệp tùy chọn, dạng ảnh hoặc PDF.')
    approved_by = UserSerializer(read_only=True, help_text='Admin đã duyệt hồ sơ.')
    approved_at = serializers.DateTimeField(read_only=True, help_text='Thời điểm hồ sơ được duyệt.')
    rejection_reason = serializers.CharField(read_only=True, allow_null=True, help_text='Lý do hồ sơ bị từ chối hoặc tạm khóa.')
    rejected_fields = serializers.DictField(read_only=True, help_text='Map field_name -> ghi chú, các field cần sửa lại khi bị từ chối.')
    average_rating = serializers.DecimalField(read_only=True, max_digits=3, decimal_places=2, help_text='Điểm đánh giá trung bình từ 0 đến 5.')
    total_completed_jobs = serializers.IntegerField(read_only=True, help_text='Tổng số công việc đã hoàn thành.')
    is_complete = serializers.BooleanField(read_only=True, help_text='True khi mọi thông tin bắt buộc để gửi duyệt đã đầy đủ.')
    missing_fields = serializers.ListField(child=serializers.CharField(), read_only=True, help_text='Tên các field còn thiếu hoặc chưa hợp lệ.')
    completion_percent = serializers.IntegerField(read_only=True, help_text='Phần trăm hoàn thiện dựa trên các field bắt buộc.')
    created_at = serializers.DateTimeField(read_only=True, help_text='Thời điểm tạo hồ sơ.')
    updated_at = serializers.DateTimeField(read_only=True, help_text='Thời điểm cập nhật hồ sơ gần nhất.')

    def validate_phone_number(self, value):
        if value == '':
            return None
        if value:
            value = value.strip()
            if not re.fullmatch(r'(?:\+84|0)\d{9}', value):
                raise serializers.ValidationError('Số điện thoại Việt Nam không hợp lệ.')
        if value and User.objects.filter(phone_number=value).exclude(pk=self.instance.user_id).exists():
            raise serializers.ValidationError('Số điện thoại này đã được sử dụng.')
        return value

    def validate_identity_number(self, value):
        if value in ('', None):
            return None
        value = value.strip()
        if not re.fullmatch(r'(?:\d{9}|\d{12})', value):
            raise serializers.ValidationError('CCCD/CMND phải gồm 9 hoặc 12 chữ số.')
        if WorkerProfile.objects.filter(identity_number=value).exclude(pk=self.instance.pk).exists():
            raise serializers.ValidationError('Số CCCD/CMND này đã được sử dụng.')
        return value

    def validate(self, attrs):
        protected_fields = {
            'role', 'status', 'approved_by', 'approved_at', 'rejection_reason',
            'rejected_fields', 'average_rating', 'total_completed_jobs',
            'created_at', 'updated_at',
        }
        attempted_fields = protected_fields.intersection(self.initial_data)
        if attempted_fields:
            raise serializers.ValidationError({
                field: 'Field này chỉ đọc và không thể cập nhật tại API hồ sơ nhân viên.'
                for field in sorted(attempted_fields)
            })
        front = attrs.get('identity_front')
        back = attrs.get('identity_back')
        if bool(front) != bool(back):
            raise serializers.ValidationError({
                'identity_documents': 'Phải gửi đồng thời ảnh mặt trước và mặt sau CCCD/CMND.',
            })
        birth_date = attrs.get('birth_date', self.instance.user.birth_date)
        if birth_date:
            today = timezone.localdate()
            age = today.year - birth_date.year - ((today.month, today.day) < (birth_date.month, birth_date.day))
            if age < 18:
                raise serializers.ValidationError({'birth_date': 'Nhân viên phải đủ 18 tuổi.'})
        return attrs

    @staticmethod
    def _save_document(user, document_type, uploaded_file, field_name):
        extension = Path(uploaded_file.name).suffix.lower()
        file_type = (
            WorkerVerificationDocument.FileType.PDF
            if extension == '.pdf'
            else WorkerVerificationDocument.FileType.IMAGE
        )
        uploaded = upload_file(
            uploaded_file,
            folder=f'{settings.CLOUDINARY_WORKER_PROFILE_FOLDER}/user_{user.id}',
            public_id_prefix=document_type.lower(),
            field_name=field_name,
            resource_type='auto' if file_type == WorkerVerificationDocument.FileType.PDF else 'image',
        )
        WorkerVerificationDocument.objects.update_or_create(
            worker=user,
            document_type=document_type,
            defaults={'file': uploaded['url'], 'file_type': file_type},
        )

    @transaction.atomic
    def update(self, instance, validated_data):
        portrait = validated_data.pop('portrait', None)
        identity_front = validated_data.pop('identity_front', None)
        identity_back = validated_data.pop('identity_back', None)
        certificate_file = validated_data.pop('certificate_file', None)

        user_fields = {'first_name', 'last_name', 'phone_number', 'gender', 'birth_date'}
        for field in list(validated_data):
            if field in user_fields:
                setattr(instance.user, field, validated_data.pop(field))
        instance.user.save()

        for field, value in validated_data.items():
            setattr(instance, field, value)
        if portrait:
            uploaded = upload_image(
                portrait,
                folder=f'{settings.CLOUDINARY_WORKER_PROFILE_FOLDER}/user_{instance.user_id}',
                public_id_prefix='portrait',
                field_name='portrait',
            )
            instance.avatar = uploaded['url']

        # Hồ sơ đang bị từ chối, worker vừa sửa lại (bất kỳ field nào) ->
        # đưa về DRAFT để có thể gửi duyệt lại qua WorkerProfileSubmitView,
        # đồng thời xoá lý do/field bị đánh dấu cũ vì đã được cập nhật.
        if instance.status == WorkerProfile.Status.REJECTED:
            instance.status = WorkerProfile.Status.DRAFT
            instance.rejection_reason = None
            instance.rejected_fields = {}

        instance.save()

        for uploaded_file, document_type, field_name in (
            (identity_front, WorkerVerificationDocument.DocumentType.IDENTITY_FRONT, 'identity_front'),
            (identity_back, WorkerVerificationDocument.DocumentType.IDENTITY_BACK, 'identity_back'),
            (certificate_file, WorkerVerificationDocument.DocumentType.CERTIFICATE, 'certificate_file'),
        ):
            if uploaded_file:
                self._save_document(instance.user, document_type, uploaded_file, field_name)
        return instance

    def to_representation(self, instance):
        documents = {
            item.document_type: item.file
            for item in instance.user.verification_documents.order_by('created_at')
        }
        completeness = get_worker_profile_completeness(instance)
        return {
            'id': instance.id,
            'user_id': instance.user_id,
            'username': instance.user.username,
            'email': instance.user.email,
            'first_name': instance.user.first_name,
            'last_name': instance.user.last_name,
            'phone_number': instance.user.phone_number,
            'gender': instance.user.gender,
            'birth_date': instance.user.birth_date,
            'role': instance.user.role,
            'status': instance.status,
            'bio': instance.bio,
            'experience_years': instance.experience_years,
            'identity_number': instance.identity_number,
            'registered_service': WorkerRegisteredServiceSerializer(
                instance.registered_service,
            ).data if instance.registered_service else None,
            'portrait': instance.avatar,
            'identity_front': documents.get(WorkerVerificationDocument.DocumentType.IDENTITY_FRONT),
            'identity_back': documents.get(WorkerVerificationDocument.DocumentType.IDENTITY_BACK),
            'certificate_file': documents.get(WorkerVerificationDocument.DocumentType.CERTIFICATE),
            'approved_by': UserSerializer(instance.approved_by).data if instance.approved_by else None,
            'approved_at': instance.approved_at,
            'rejection_reason': instance.rejection_reason,
            'rejected_fields': instance.rejected_fields or {},
            'average_rating': instance.average_rating,
            'total_completed_jobs': instance.total_completed_jobs,
            **completeness,
            'created_at': instance.created_at,
            'updated_at': instance.updated_at,
        }


class AdminWorkerStatusUpdateSerializer(serializers.Serializer):
    ADMIN_ALLOWED_STATUSES = {
        WorkerProfile.Status.ACTIVE,
        WorkerProfile.Status.REJECTED,
        WorkerProfile.Status.SUSPENDED,
    }
    # Chỉ cho phép admin chuyển đến 3 trạng thái này, không cho set DRAFT/PENDING
    status = serializers.ChoiceField(choices=[(s, s) for s in ADMIN_ALLOWED_STATUSES])
    reason = serializers.CharField(required=False, allow_blank=False)
    rejected_fields = serializers.DictField(
        child=serializers.CharField(allow_blank=False),
        required=False,
    )

    def validate_rejected_fields(self, value):
        invalid = set(value) - REJECTABLE_PROFILE_FIELDS
        if invalid:
            raise serializers.ValidationError(f"Field không hợp lệ: {', '.join(sorted(invalid))}.")
        return value

    def validate(self, attrs):
        target = attrs['status']
        current = self.instance.status

        # Chỉ approve/reject khi hồ sơ đang PENDING; chỉ suspend khi đang ACTIVE
        if target in (WorkerProfile.Status.ACTIVE, WorkerProfile.Status.REJECTED):
            if current != WorkerProfile.Status.PENDING:
                raise serializers.ValidationError({
                    'status': f'Chỉ hồ sơ đang PENDING mới được duyệt/từ chối (hiện tại: {current}).',
                })
        elif target == WorkerProfile.Status.SUSPENDED:
            if current != WorkerProfile.Status.ACTIVE:
                raise serializers.ValidationError({
                    'status': f'Chỉ hồ sơ đang ACTIVE mới được tạm khóa (hiện tại: {current}).',
                })

        if target == WorkerProfile.Status.REJECTED:
            if not attrs.get('reason'):
                raise serializers.ValidationError({'reason': 'Vui lòng nhập lý do từ chối hồ sơ.'})
            if not attrs.get('rejected_fields'):
                raise serializers.ValidationError({'rejected_fields': 'Vui lòng đánh dấu ít nhất một trường cần sửa.'})
        elif target == WorkerProfile.Status.SUSPENDED:
            if not attrs.get('reason'):
                raise serializers.ValidationError({'reason': 'Vui lòng nhập lý do tạm khóa.'})

        return attrs

    @transaction.atomic
    def update(self, instance, validated_data):
        instance = WorkerProfile.objects.select_for_update().get(pk=instance.pk)
        target_status = validated_data['status']
        reason = validated_data.get('reason')
        instance.status = target_status
        instance.approved_by = None
        instance.approved_at = None
        instance.rejection_reason = None
        instance.rejected_fields = {}
        if target_status == WorkerProfile.Status.ACTIVE:
            instance.approved_by = self.context['request'].user
            instance.approved_at = timezone.now()
        elif target_status == WorkerProfile.Status.REJECTED:
            instance.rejection_reason = reason
            instance.rejected_fields = validated_data.get('rejected_fields', {})
        elif target_status == WorkerProfile.Status.SUSPENDED:
            instance.rejection_reason = reason
        instance.save()
        return instance


class ForgotPasswordSerializer(serializers.Serializer):
    email = serializers.EmailField(required=True)

    def validate_email(self, value):
        return value.strip().lower()

    def get_user(self):
        return User.objects.filter(
            email__iexact=self.validated_data['email'],
            is_active=True,
        ).first()


class VerifyPasswordResetOTPSerializer(serializers.Serializer):
    email = serializers.EmailField(required=True, write_only=True)
    code = serializers.RegexField(regex=r'^\d{6}$', required=True, write_only=True)

    def validate_email(self, value):
        return value.strip().lower()

    def validate(self, attrs):
        user = User.objects.filter(email__iexact=attrs['email'], is_active=True).first()
        otp = None
        if user:
            otp = PasswordResetOTP.objects.filter(
                user=user,
                used_at__isnull=True,
            ).order_by('-created_at').first()
        if not otp or otp.is_expired or otp.attempts >= settings.PASSWORD_RESET_OTP_MAX_ATTEMPTS:
            raise serializers.ValidationError({'code': 'Mã xác thực không hợp lệ hoặc đã hết hạn.'})
        if not otp.check_code(attrs['code']):
            otp.attempts += 1
            otp.save(update_fields=['attempts'])
            raise serializers.ValidationError({'code': 'Mã xác thực không hợp lệ hoặc đã hết hạn.'})
        attrs['otp'] = otp
        return attrs

    def save(self, **kwargs):
        otp = self.validated_data['otp']
        if not otp.is_verified:
            otp.mark_verified()
        return otp


class ResetPasswordSerializer(serializers.Serializer):
    email = serializers.EmailField(required=True, write_only=True)
    code = serializers.RegexField(regex=r'^\d{6}$', required=True, write_only=True)
    new_password = serializers.CharField(
        required=True,
        write_only=True,
        style={'input_type': 'password'},
        validators=[validate_password],
    )
    new_password_confirm = serializers.CharField(
        required=True,
        write_only=True,
        style={'input_type': 'password'},
    )

    def validate_email(self, value):
        return value.strip().lower()

    def validate(self, attrs):
        if attrs['new_password'] != attrs['new_password_confirm']:
            raise serializers.ValidationError({'new_password_confirm': 'Mật khẩu xác nhận không khớp.'})
        user = User.objects.filter(email__iexact=attrs['email'], is_active=True).first()
        otp = None
        if user:
            otp = PasswordResetOTP.objects.filter(
                user=user,
                used_at__isnull=True,
            ).order_by('-created_at').first()
        if (
            not otp
            or otp.is_expired
            or not otp.is_verified
            or otp.attempts >= settings.PASSWORD_RESET_OTP_MAX_ATTEMPTS
        ):
            raise serializers.ValidationError({'code': 'Vui lòng xác minh mã OTP trước khi đặt lại mật khẩu.'})
        if not otp.check_code(attrs['code']):
            otp.attempts += 1
            otp.save(update_fields=['attempts'])
            raise serializers.ValidationError({'code': 'Mã xác thực không hợp lệ hoặc đã hết hạn.'})
        attrs['user'] = user
        attrs['otp'] = otp
        return attrs

    def save(self, **kwargs):
        user = self.validated_data['user']
        user.set_password(self.validated_data['new_password'])
        user.save(update_fields=['password'])
        self.validated_data['otp'].mark_used()
        return user


class TokenResponseSerializer(serializers.Serializer):
    access = serializers.CharField()
    refresh = serializers.CharField()
    user = serializers.DictField()
    is_new_user = serializers.BooleanField(required=False)


class WorkerProfileSummaryResponseSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    status = serializers.ChoiceField(choices=WorkerProfile.Status.choices)


class WorkerRegisterResponseSerializer(TokenResponseSerializer):
    worker_profile = WorkerProfileSummaryResponseSerializer()