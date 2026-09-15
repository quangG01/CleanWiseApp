from .models import WorkerVerificationDocument


DOCUMENT_FIELD_MAP = {
    'identity_front': WorkerVerificationDocument.DocumentType.IDENTITY_FRONT,
    'identity_back': WorkerVerificationDocument.DocumentType.IDENTITY_BACK,
    'certificate_file': WorkerVerificationDocument.DocumentType.CERTIFICATE,
}


def get_worker_profile_completeness(profile):
    required = {
        'identity_number': profile.identity_number,
        'avatar': profile.avatar,
    }
    missing = [name for name, value in required.items() if not value]
    return {
        'is_complete': not missing,
        'missing_fields': missing,
        'completion_percent': round((len(required) - len(missing)) * 100 / len(required)),
    }
