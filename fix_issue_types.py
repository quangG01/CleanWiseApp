from apps.complaints.models import ComplaintIssueType as T

CUSTOMER = [
    'WORKER_NOT_ARRIVED',
    'WORKER_LATE',
    'CANNOT_CONTACT_WORKER',
    'SERVICE_NOT_AS_REQUESTED',
    'MISSING_SERVICE_ITEM',
    'WORKER_BEHAVIOR',
    'PROPERTY_DAMAGE',
    'SERVICE_QUALITY',
    'MISSING_SERVICE_ITEM_AFTER',
    'PROPERTY_DAMAGE_AFTER',
    'MISSING_PROPERTY',
    'PAYMENT_PROBLEM',
]

T.objects.filter(
    code__in=CUSTOMER
).update(
    applies_to='CUSTOMER'
)

T.objects.filter(
    code__in=[
        'BOOKING_INFORMATION',
        'SAFETY_PROBLEM',
        'APP_PROBLEM',
        'OTHER',
    ]
).update(
    applies_to='ANY'
)

T.objects.filter(
    code='LEGACY_OTHER'
).update(
    is_active=False
)

WORKER = [
    (
        'CUSTOMER_NOT_PAY',
        'Khách không thanh toán tiền mặt',
        'Đã hoàn thành dịch vụ nhưng khách không trả tiền.',
    ),
    (
        'CUSTOMER_ABSENT',
        'Khách vắng mặt / không mở cửa',
        'Đến đúng giờ nhưng không gặp được khách.',
    ),
    (
        'CANNOT_CONTACT_CUSTOMER',
        'Không liên hệ được khách',
        'Gọi hoặc nhắn tin nhưng khách không phản hồi.',
    ),
    (
        'WRONG_ADDRESS',
        'Sai địa chỉ / thông tin đơn',
        'Địa chỉ hoặc thông tin trong đơn không đúng thực tế.',
    ),
    (
        'CUSTOMER_BEHAVIOR',
        'Khách có thái độ không phù hợp',
        'Khách có lời nói, hành vi thiếu tôn trọng hoặc gây khó chịu.',
    ),
    (
        'OUT_OF_SCOPE_REQUEST',
        'Khách yêu cầu ngoài phạm vi dịch vụ',
        'Khách đòi thêm việc không có trong đơn.',
    ),
    (
        'WORKER_PAYMENT_PROBLEM',
        'Thu nhập / thanh toán cho nhân viên có vấn đề',
        'Thu nhập sai hoặc chưa nhận được tiền.',
    ),
    (
        'AUTO_CANCELLED_WORKED',
        'Đã làm nhưng đơn bị tự hủy',
        'Bạn đã đến làm nhưng không check-in được nên hệ thống tự hủy buổi.',
    ),
]

for code, name, desc in WORKER:
    T.objects.update_or_create(
        code=code,
        defaults={
            'name': name,
            'description': desc,
            'stage': 'ANY',
            'applies_to': 'WORKER',
            'is_active': True,
        },
    )

for t in T.objects.order_by('applies_to', 'id'):
    print(
        t.id,
        t.code,
        '|',
        t.name,
        '|',
        t.applies_to,
        '|',
        'on' if t.is_active else 'off',
    )