"""Lightweight view decorators kept separate from the authentication behavior."""


def _schema(view_class):
    return view_class


USER_LIST_SCHEMA = _schema
LOGIN_SCHEMA = _schema
REGISTER_SCHEMA = _schema
GOOGLE_LOGIN_SCHEMA = _schema
FORGOT_PASSWORD_SCHEMA = _schema
VERIFY_PASSWORD_RESET_OTP_SCHEMA = _schema
RESET_PASSWORD_SCHEMA = _schema
CUSTOMER_PROFILE_SCHEMA = _schema
WORKER_REGISTER_SCHEMA = _schema
WORKER_PROFILE_SCHEMA = _schema
ADMIN_WORKER_PROFILE_LIST_SCHEMA = _schema
ADMIN_WORKER_STATUS_UPDATE_SCHEMA = _schema
