from .models import WorkerVerificationDocument


DOCUMENT_FIELD_MAP = {
    'identity_front': WorkerVerificationDocument.DocumentType.IDENTITY_FRONT,
    'identity_back': WorkerVerificationDocument.DocumentType.IDENTITY_BACK,
    'certificate_file': WorkerVerificationDocument.DocumentType.CERTIFICATE,
}


def get_worker_profile_completeness(profile):
    document_types = {
        document.document_type
        for document in profile.user.verification_documents.all()
    }
    registered_service_is_active = bool(
        profile.registered_service_id
        and profile.registered_service
        and profile.registered_service.is_active
    )
    required = {
        'first_name': profile.user.first_name.strip(),
        'last_name': profile.user.last_name.strip(),
        'phone_number': profile.user.phone_number,
        'gender': profile.user.gender,
        'birth_date': profile.user.birth_date,
        'identity_number': profile.identity_number,
        'portrait': profile.avatar,
        'service_id': registered_service_is_active,
        'identity_front': WorkerVerificationDocument.DocumentType.IDENTITY_FRONT in document_types,
        'identity_back': WorkerVerificationDocument.DocumentType.IDENTITY_BACK in document_types,
        'working_areas': profile.user.working_areas.filter(area__is_active=True).exists(),
    }
    missing = [name for name, value in required.items() if not value]
    return {
        'is_complete': not missing,
        'missing_fields': missing,
        'completion_percent': round((len(required) - len(missing)) * 100 / len(required)),
    }
