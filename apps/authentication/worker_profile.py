from .models import WorkerVerificationDocument


DOCUMENT_REQUIRED_FIELDS = {
    "identity_front": WorkerVerificationDocument.DocumentType.IDENTITY_FRONT,
    "identity_back": WorkerVerificationDocument.DocumentType.IDENTITY_BACK,
    "certificate_file": WorkerVerificationDocument.DocumentType.CERTIFICATE,
}


def get_worker_profile_completeness(profile):
    values = {
        "phone_number": profile.user.phone_number,
        "full_name": profile.full_name,
        "gender": profile.gender,
        "birth_date": profile.birth_date,
        "identity_number": profile.identity_number,
        "identity_issued_date": profile.identity_issued_date,
        "identity_issued_place": profile.identity_issued_place,
        "avatar": profile.avatar,
        "province": profile.province,
        "ward": profile.ward,
        "address_line": profile.address_line,
        "certificate_number": profile.certificate_number,
        "certificate_expiry_date": profile.certificate_expiry_date,
        "bank_code": profile.bank_code,
        "bank_account_number": profile.bank_account_number_encrypted,
        "bank_account_holder": profile.bank_account_holder,
        "terms_accepted": profile.terms_accepted_at,
    }

    document_types = set(
        profile.user.verification_documents.filter(
            document_type__in=DOCUMENT_REQUIRED_FIELDS.values()
        ).values_list("document_type", flat=True)
    )
    for field_name, document_type in DOCUMENT_REQUIRED_FIELDS.items():
        values[field_name] = document_type in document_types

    missing_fields = [name for name, value in values.items() if not value]
    total = len(values)
    completed = total - len(missing_fields)

    return {
        "is_complete": not missing_fields,
        "completion_percent": round(completed * 100 / total),
        "missing_fields": missing_fields,
    }
