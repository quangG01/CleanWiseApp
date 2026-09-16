"""OpenAPI decorators kept separate from the authentication behavior."""

from rest_framework import serializers
from drf_spectacular.utils import extend_schema, extend_schema_view, inline_serializer

from .serializers import (
    CustomerRegisterSerializer,
    TokenResponseSerializer,
    WorkerRegisterResponseSerializer,
    WorkerRegisterSerializer,
)


def _schema(view_class):
    return view_class


USER_LIST_SCHEMA = _schema
LOGIN_SCHEMA = _schema
CUSTOMER_REGISTER_SCHEMA = extend_schema_view(
    post=extend_schema(
        request=CustomerRegisterSerializer,
        responses={
            201: inline_serializer(
                name='CustomerRegisterSuccessResponse',
                fields={
                    'message': serializers.CharField(),
                    'data': TokenResponseSerializer(),
                },
            ),
        },
        description='Đăng ký khách hàng. Role luôn được backend gán là CUSTOMER.',
    ),
)
GOOGLE_LOGIN_SCHEMA = _schema
FORGOT_PASSWORD_SCHEMA = _schema
VERIFY_PASSWORD_RESET_OTP_SCHEMA = _schema
RESET_PASSWORD_SCHEMA = _schema
CUSTOMER_PROFILE_SCHEMA = _schema
WORKER_REGISTER_SCHEMA = extend_schema_view(
    post=extend_schema(
        request=WorkerRegisterSerializer,
        responses={
            201: inline_serializer(
                name='WorkerRegisterSuccessResponse',
                fields={
                    'message': serializers.CharField(),
                    'data': WorkerRegisterResponseSerializer(),
                },
            ),
        },
        description=(
            'Đăng ký nhân viên. Role luôn là WORKER và hồ sơ nhân viên '
            'được tạo ở trạng thái PENDING.'
        ),
    ),
)
WORKER_PROFILE_SCHEMA = _schema
ADMIN_WORKER_PROFILE_LIST_SCHEMA = _schema
ADMIN_WORKER_STATUS_UPDATE_SCHEMA = _schema
