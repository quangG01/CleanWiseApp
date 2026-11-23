import hashlib
import json
from datetime import datetime, time, timedelta
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

from django.contrib.auth.hashers import make_password
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

PASSWORD = '123456789Aa@'
SECTIONS = ['HOME_CLEANING', 'APPLIANCE_CLEANING', 'MOVING', 'UPHOLSTERY_CLEANING']
DEMO_BOOKING_PREFIX = 'DEMO-CW-'
DEMO_BOOKING_COUNT = 600
NEW_WORKER_BOOKINGS_PER_ACCOUNT = 5
DEMO_SEED_KEY_PREFIX = 'seed_demo.booking:'
LEGACY_NEW_WORKER_SEED_KEY_PREFIX = 'seed_demo.worker_booking:'

CUSTOMERS = [
    ('0961439551', 'Phạm Khả Hào', 'M'), ('0961439552', 'Nguyễn Minh Khang', 'M'),
    ('0961439553', 'Trần Quốc Bảo', 'M'), ('0961439554', 'Lê Hoàng Phúc', 'M'),
    ('0961439555', 'Nguyễn Thị Lan Anh', 'F'), ('0961439556', 'Trần Ngọc Mai', 'F'),
    ('0961439557', 'Lê Thu Hà', 'F'), ('0961439558', 'Phạm Thanh Trúc', 'F'),
]
WORKERS = [
    ('0961439559', 'Võ Văn Thành', 'M'), ('0961439560', 'Đặng Quốc Huy', 'M'),
    ('0961439561', 'Bùi Minh Tuấn', 'M'), ('0961439562', 'Hồ Gia Bảo', 'M'),
    ('0961439563', 'Nguyễn Thị Hương', 'F'), ('0961439564', 'Lâm Thị Thu', 'F'),
    ('0961439565', 'Trần Thị Kim Ngân', 'F'), ('0961439566', 'Phan Thị Yến Nhi', 'F'),
]
NEW_WORKERS = [
    ('0961439567', 'Lê Quốc Đạt', 'M'), ('0961439568', 'Nguyễn Văn Khôi', 'M'),
    ('0961439569', 'Phan Đức Long', 'M'), ('0961439570', 'Trần Minh Nhật', 'M'),
    ('0961439571', 'Hoàng Thị Mỹ Duyên', 'F'), ('0961439572', 'Vũ Ngọc Diệp', 'F'),
    ('0961439573', 'Bùi Thanh Thảo', 'F'), ('0961439574', 'Đỗ Khánh Linh', 'F'),
]
DEMO_EMAILS = {
    '0961439551': 'phamkhahao@gmail.com',
    '0961439552': 'nguyenminhkhang@gmail.com',
    '0961439553': 'tranquocbao@gmail.com',
    '0961439554': 'lehoangphuc@gmail.com',
    '0961439555': 'nguyenthilananh@gmail.com',
    '0961439556': 'tranngocmai@gmail.com',
    '0961439557': 'lethuha@gmail.com',
    '0961439558': 'phamthanhtruc@gmail.com',
    '0961439559': 'vovanthanh@gmail.com',
    '0961439560': 'dangquochuy@gmail.com',
    '0961439561': 'buiminhtuan@gmail.com',
    '0961439562': 'hogiabao@gmail.com',
    '0961439563': 'nguyenthihuong@gmail.com',
    '0961439564': 'lamthithu@gmail.com',
    '0961439565': 'tranthikimngan@gmail.com',
    '0961439566': 'phanthiyennhi@gmail.com',
    '0961439567': 'lequocdat@gmail.com',
    '0961439568': 'nguyenvankhoi@gmail.com',
    '0961439569': 'phanduclong@gmail.com',
    '0961439570': 'tranminhnhat@gmail.com',
    '0961439571': 'hoangthimyduyen@gmail.com',
    '0961439572': 'vungocdiep@gmail.com',
    '0961439573': 'buithanhthao@gmail.com',
    '0961439574': 'dokhanhlinh@gmail.com',
}
DEMO_NAME_PARTS = {
    'Phạm Khả Hào': ('Hào', 'Phạm Khả'),
    'Nguyễn Minh Khang': ('Khang', 'Nguyễn Minh'),
    'Trần Quốc Bảo': ('Bảo', 'Trần Quốc'),
    'Lê Hoàng Phúc': ('Phúc', 'Lê Hoàng'),
    'Nguyễn Thị Lan Anh': ('Lan Anh', 'Nguyễn Thị'),
    'Trần Ngọc Mai': ('Mai', 'Trần Ngọc'),
    'Lê Thu Hà': ('Hà', 'Lê Thu'),
    'Phạm Thanh Trúc': ('Trúc', 'Phạm Thanh'),
    'Võ Văn Thành': ('Thành', 'Võ Văn'),
    'Đặng Quốc Huy': ('Huy', 'Đặng Quốc'),
    'Bùi Minh Tuấn': ('Tuấn', 'Bùi Minh'),
    'Hồ Gia Bảo': ('Bảo', 'Hồ Gia'),
    'Nguyễn Thị Hương': ('Hương', 'Nguyễn Thị'),
    'Lâm Thị Thu': ('Thu', 'Lâm Thị'),
    'Trần Thị Kim Ngân': ('Kim Ngân', 'Trần Thị'),
    'Phan Thị Yến Nhi': ('Yến Nhi', 'Phan Thị'),
    'Lê Quốc Đạt': ('Đạt', 'Lê Quốc'),
    'Nguyễn Văn Khôi': ('Khôi', 'Nguyễn Văn'),
    'Phan Đức Long': ('Long', 'Phan Đức'),
    'Trần Minh Nhật': ('Nhật', 'Trần Minh'),
    'Hoàng Thị Mỹ Duyên': ('Duyên', 'Hoàng Thị Mỹ'),
    'Vũ Ngọc Diệp': ('Diệp', 'Vũ Ngọc'),
    'Bùi Thanh Thảo': ('Thảo', 'Bùi Thanh'),
    'Đỗ Khánh Linh': ('Linh', 'Đỗ Khánh'),
}


def new_worker_seed_key(worker_index, booking_index):
    return f'{LEGACY_NEW_WORKER_SEED_KEY_PREFIX}{worker_index:02d}:{booking_index:02d}'


def base_booking_seed_key(index):
    return f'{DEMO_SEED_KEY_PREFIX}base:{index:06d}'


def split_demo_name(full_name):
    parts = DEMO_NAME_PARTS.get(full_name)
    if parts is None:
        raise CommandError(f'Tên demo không hợp lệ: {full_name}')
    return parts


def demo_booking_ids():
    from django.db.models import Q

    from apps.bookings.models import Booking, BookingActivity

    marker_ids = BookingActivity.objects.filter(
        Q(metadata__seed_key__startswith=DEMO_SEED_KEY_PREFIX)
        | Q(metadata__seed_key__startswith=LEGACY_NEW_WORKER_SEED_KEY_PREFIX),
    ).values_list('booking_id', flat=True)
    legacy_ids = Booking.objects.filter(
        booking_code__startswith=DEMO_BOOKING_PREFIX,
    ).values_list('pk', flat=True)
    return list(set(marker_ids) | set(legacy_ids))
ADDRESSES = [
    dict(label='Nhà', address_line='5X Đường Thới Tam Thôn 16', ward='Xã Đông Thạnh',
         ward_code='27568', latitude='10.8863815', longitude='106.6203860', is_default=True),
    dict(label='Trường', address_line='Nguyễn Văn Bảo', ward='Phường Hạnh Thông',
         ward_code='26890', latitude='10.8224256', longitude='106.6868920', is_default=False),
]
BIOS = [
    'Làm việc cẩn thận, đúng giờ, ưu tiên sạch sẽ và gọn gàng.',
    'Nhiều năm kinh nghiệm, thân thiện và có trách nhiệm với từng buổi làm.',
    'Chú trọng chi tiết, luôn mang đủ dụng cụ và vật tư khi đến nhà khách.',
    'Nhanh nhẹn, trung thực, sẵn sàng làm các khung giờ linh hoạt.',
]
REVIEW_COMMENTS = [
    'Nhân viên đến đúng giờ, làm việc kỹ và rất lịch sự.',
    'Nhà cửa sạch sẽ hơn mong đợi, tôi sẽ tiếp tục đặt lịch.',
    'Dịch vụ tốt, các góc khó vệ sinh cũng được chú ý.',
    'Làm việc gọn gàng, trao đổi rõ ràng trước khi bắt đầu.',
    'Hoàn thành đúng thời gian và để lại không gian ngăn nắp.',
]
COMPLAINT_TEXTS = [
    'Một vài vị trí chưa được vệ sinh kỹ như mong muốn, nhờ CleanWise hỗ trợ kiểm tra.',
    'Tôi muốn được tư vấn thêm về hạng mục đã thực hiện trong buổi này.',
    'Phát sinh một điểm cần trao đổi sau khi nghiệm thu dịch vụ.',
]
DEMO_MEDIA_PATHS = [
    'avatars/customers/customer_01_nam.jpg',
    'avatars/customers/customer_02_nam.jpg',
    'avatars/customers/customer_03_nam.jpg',
    'avatars/customers/customer_04_nam.jpg',
    'avatars/customers/customer_05_nu.jpg',
    'avatars/customers/customer_06_nu.jpg',
    'avatars/customers/customer_07_nu.jpg',
    'avatars/customers/customer_08_nu.jpg',
    'avatars/workers/worker_01_nam.jpg',
    'avatars/workers/worker_02_nam.jpg',
    'avatars/workers/worker_03_nam.jpg',
    'avatars/workers/worker_04_nam.jpg',
    'avatars/workers/worker_05_nu.jpg',
    'avatars/workers/worker_06_nu.jpg',
    'avatars/workers/worker_07_nu.jpg',
    'avatars/workers/worker_08_nu.jpg',
    'worker_docs/identity_front.jpg',
    'worker_docs/identity_back.jpg',
    'worker_docs/certificate.jpg',
    'reviews/r_01.jpg', 'reviews/r_02.jpg', 'reviews/r_03.jpg',
    'reviews/r_04.jpg', 'reviews/r_05.jpg', 'reviews/r_06.jpg',
    'complaints/c_01.jpg', 'complaints/c_02.jpg', 'complaints/c_03.jpg',
    'complaints/c_04.jpg', 'complaints/c_05.jpg', 'complaints/c_06.jpg',
    'complaints/c_07.jpg', 'complaints/c_08.jpg',
    'schedule_photos/HOME_CLEANING/before_01.jpg',
    'schedule_photos/HOME_CLEANING/after_01.jpg',
    'schedule_photos/APPLIANCE_CLEANING/before_01.jpg',
    'schedule_photos/APPLIANCE_CLEANING/after_01.jpg',
]


def field_names(model):
    return {f.name for f in model._meta.concrete_fields}


def pick_role(User, word):
    choices = [c[0] for c in User._meta.get_field('role').choices]
    for choice in choices:
        if word in str(choice).upper():
            return choice
    raise CommandError(f'Không tìm thấy role chứa "{word}" trong {choices}')


def gender_value(User, gender):
    choices = [str(c[0]) for c in User._meta.get_field('gender').choices]
    want = ('MALE', 'M', 'NAM') if gender == 'M' else ('FEMALE', 'F', 'NU', 'NỮ')
    for choice in choices:
        if choice.upper() in want:
            return choice
    raise CommandError(f'Không khớp gender trong {choices}')


def _sha1(path):
    digest = hashlib.sha1()
    with path.open('rb') as image_file:
        for chunk in iter(lambda: image_file.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def load_demo_media(*, commit):
    from django.conf import settings

    root = Path(settings.BASE_DIR) / 'demo_images'
    manifest_path = root / '_uploaded.json'
    if not root.is_dir():
        raise CommandError(f'Không tìm thấy thư mục ảnh demo: {root}')
    try:
        manifest = json.loads(manifest_path.read_text(encoding='utf-8')) if manifest_path.exists() else {}
    except (OSError, json.JSONDecodeError) as exc:
        raise CommandError(f'Không đọc được manifest ảnh demo {manifest_path}: {exc}') from exc

    media_urls = {}
    missing = []
    for relative_path in DEMO_MEDIA_PATHS:
        path = root / Path(relative_path)
        if not path.is_file():
            raise CommandError(f'Thiếu ảnh demo: {path}')
        entry = manifest.get(relative_path, {})
        if entry.get('sha1') == _sha1(path) and entry.get('url', '').startswith('https://'):
            media_urls[relative_path] = entry['url']
        else:
            missing.append((relative_path, path))

    if missing and not commit:
        names = ', '.join(relative_path for relative_path, _ in missing)
        raise CommandError(
            'Dry-run không upload Cloudinary. Các ảnh sau chưa có URL hợp lệ trong manifest: '
            f'{names}. Chạy --commit sau khi xác nhận để upload.'
        )

    if missing:
        from apps.common.cloudinary_storage import upload_image

        for relative_path, path in missing:
            folder = 'cleanwise_demo/' + relative_path.rsplit('/', 1)[0]
            with path.open('rb') as image_file:
                uploaded = upload_image(
                    image_file,
                    folder=folder,
                    public_id_prefix=path.stem,
                )
            manifest[relative_path] = {
                'url': uploaded['url'],
                'public_id': uploaded['public_id'],
                'sha1': _sha1(path),
            }
            media_urls[relative_path] = uploaded['url']
            manifest_path.write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2),
                encoding='utf-8',
            )

    return media_urls


def seed_users(command):
    from apps.addresses.models import CustomerAddress
    from apps.authentication.models import User, WorkerProfile
    from apps.services.models import Service
    from apps.worker.models import Area, WorkerWorkingArea

    services = {}
    for section in SECTIONS:
        service = Service.objects.filter(section_code=section, is_active=True).order_by('id').first()
        if not service:
            raise CommandError(f'Không có dịch vụ active cho {section}')
        services[section] = service
    core_areas = list(Area.objects.filter(ward_code__in=['27568', '26890']))
    if len(core_areas) != 2:
        raise CommandError('Thiếu Area 27568 / 26890')
    neighbor_areas = list(
        Area.objects.filter(province_code='79')
        .exclude(ward_code__in=['27568', '26890'])
        .order_by('ward_code')[:6]
    )
    work_areas = core_areas + neighbor_areas

    original_usernames = [phone for phone, _, _ in CUSTOMERS + WORKERS]
    demo_usernames = original_usernames + [phone for phone, _, _ in NEW_WORKERS]
    if set(DEMO_EMAILS) != set(demo_usernames) or len(set(DEMO_EMAILS.values())) != len(DEMO_EMAILS):
        raise CommandError('Danh sách email demo thiếu hoặc bị trùng.')
    email_owners = {
        user.email: user.username
        for user in User.objects.filter(email__in=DEMO_EMAILS.values())
    }
    for phone, email in DEMO_EMAILS.items():
        if email in email_owners and email_owners[email] != phone:
            raise CommandError(
                f'Email demo {email} đang thuộc tài khoản {email_owners[email]}; '
                'không ghi đè tài khoản khác.'
            )
    original_users = {
        user.username: user
        for user in User.objects.filter(username__in=original_usernames)
    }
    missing_original = sorted(set(original_usernames) - set(original_users))
    if missing_original:
        raise CommandError(
            'Không tìm thấy đủ 8 customer và 8 worker hiện có; không tự tạo hoặc sửa tài khoản cũ: '
            f'{missing_original}'
        )
    for phone, _, _ in CUSTOMERS:
        if original_users[phone].role != User.Role.CUSTOMER:
            raise CommandError(f'Tài khoản customer hiện có {phone} không đúng role.')
    old_workers = [original_users[phone] for phone, _, _ in WORKERS]
    invalid_old_workers = [
        worker.username for worker in old_workers if worker.role != User.Role.WORKER
    ]
    if invalid_old_workers:
        raise CommandError(
            f'Tài khoản worker hiện có sai role: {invalid_old_workers}; không thay đổi tài khoản.'
        )
    customers = [original_users[phone] for phone, _, _ in CUSTOMERS]
    for phone, full_name, _ in CUSTOMERS + WORKERS:
        user = original_users[phone]
        first_name, last_name = split_demo_name(full_name)
        User.objects.filter(pk=user.pk).update(
            email=DEMO_EMAILS[phone],
            first_name=first_name,
            last_name=last_name,
        )
        user.email = DEMO_EMAILS[phone]
        user.first_name = first_name
        user.last_name = last_name

    new_workers = []
    created_count = 0
    password_hash = make_password(PASSWORD)
    for phone, name, gender in NEW_WORKERS:
        first_name, last_name = split_demo_name(name)
        worker, created = User.objects.get_or_create(
            username=phone,
            defaults={
                'email': DEMO_EMAILS[phone],
                'role': User.Role.WORKER,
                'is_active': True,
                'password': password_hash,
                'phone_number': phone,
                'first_name': first_name,
                'last_name': last_name,
                'gender': gender_value(User, gender),
            },
        )
        if not created and (
            worker.role != User.Role.WORKER
            or worker.phone_number != phone
            or not worker.is_active
            or worker.gender != gender_value(User, gender)
            or not worker.check_password(PASSWORD)
        ):
            raise CommandError(
                f'Tài khoản {phone} đã tồn tại nhưng không phải tài khoản demo này; '
                'không thay đổi thông tin đăng nhập.'
            )
        User.objects.filter(pk=worker.pk).update(
            email=DEMO_EMAILS[phone],
            first_name=first_name,
            last_name=last_name,
        )
        worker.email = DEMO_EMAILS[phone]
        worker.first_name = first_name
        worker.last_name = last_name
        created_count += int(created)
        new_workers.append(worker)

    addresses_by_customer = {}
    for address in CustomerAddress.objects.filter(
        customer__in=customers,
        is_active=True,
    ).order_by('-is_default', 'id'):
        addresses_by_customer.setdefault(address.customer_id, []).append(address)
    missing_addresses = [
        customer.username for customer in customers
        if not addresses_by_customer.get(customer.pk)
    ]
    if missing_addresses:
        raise CommandError(
            f'Thiếu địa chỉ cho customer hiện có {missing_addresses}; '
            'command không sửa dữ liệu customer.'
        )

    old_profiles = {
        profile.user_id: profile
        for profile in WorkerProfile.objects.filter(user__in=old_workers).select_related(
            'registered_service',
        )
    }
    missing_profiles = [worker.username for worker in old_workers if worker.pk not in old_profiles]
    if missing_profiles:
        raise CommandError(
            f'Thiếu WorkerProfile của worker hiện có {missing_profiles}; '
            'command không tạo lại hoặc thay đổi hồ sơ cũ.'
        )
    workers_by_section = {section: [] for section in SECTIONS}
    for worker in old_workers:
        profile = old_profiles[worker.pk]
        if not profile.registered_service_id or profile.registered_service.section_code not in SECTIONS:
            raise CommandError(f'Worker {worker.username} chưa đăng ký dịch vụ hợp lệ.')
        workers_by_section[profile.registered_service.section_code].append(worker)

    admin = User.objects.filter(role=User.Role.ADMIN, is_active=True).order_by('id').first()
    missing_new_profiles = []
    for index, worker in enumerate(new_workers):
        profile_values = {
            'registered_service': services['HOME_CLEANING'],
            'status': WorkerProfile.Status.ACTIVE,
            'identity_number': f'0792{worker.username[-8:]}',
            'bio': BIOS[index % len(BIOS)],
            'experience_years': 2 + (index % 5),
            'approved_by': admin,
            'approved_at': timezone.now() if admin else None,
        }
        profile = WorkerProfile.objects.filter(user=worker).first()
        if profile is None:
            missing_new_profiles.append(WorkerProfile(user=worker, **profile_values))
        else:
            profile_values['approved_by'] = profile.approved_by or admin
            profile_values['approved_at'] = profile.approved_at or (
                timezone.now() if admin else None
            )
            WorkerProfile.objects.filter(pk=profile.pk).update(**profile_values)
        workers_by_section['HOME_CLEANING'].append(worker)
        for area in work_areas:
            WorkerWorkingArea.objects.get_or_create(worker=worker, area=area)
    if missing_new_profiles:
        WorkerProfile.objects.bulk_create(missing_new_profiles, batch_size=100)

    worker_area_codes = {}
    for worker_id, ward_code in WorkerWorkingArea.objects.filter(
        worker__in=old_workers + new_workers,
    ).values_list('worker_id', 'area__ward_code'):
        worker_area_codes.setdefault(worker_id, set()).add(ward_code)

    command.stdout.write(
        f'Giữ nguyên {len(customers)} customer và {len(old_workers)} worker cũ; '
        f'{created_count} worker mới được tạo, tổng worker {len(old_workers) + len(new_workers)}; '
        f'{len(work_areas)} khu vực/worker mới.'
    )
    command.stdout.write(
        'Tài khoản worker mới: ' + ', '.join(
            f'{phone} / {PASSWORD} / {DEMO_EMAILS[phone]}'
            for phone, _, _ in NEW_WORKERS
        )
    )
    return {
        'customers': customers,
        'workers': old_workers + new_workers,
        'old_workers': old_workers,
        'new_workers': new_workers,
        'services': services,
        'addresses': addresses_by_customer,
        'workers_by_section': workers_by_section,
        'work_areas': work_areas,
        'worker_area_codes': worker_area_codes,
    }


def _workers_for_demo_address(demo, section, address):
    candidates = [
        worker for worker in demo['workers_by_section'][section]
        if address.ward_code in demo['worker_area_codes'].get(worker.pk, set())
    ]
    if not candidates:
        raise CommandError(
            f'Không có worker đăng ký đúng dịch vụ và khu vực {address.ward_code}.'
        )
    return candidates


def _seed_users_legacy(command):
    from apps.addresses.models import CustomerAddress
    from apps.authentication.models import User, WorkerProfile
    from apps.services.models import Service
    from apps.worker.models import Area, WorkerWorkingArea

    role_customer = pick_role(User, 'CUSTOMER')
    role_worker = pick_role(User, 'WORKER')
    password = make_password(PASSWORD)

    services = {}
    for section in SECTIONS:
        service = Service.objects.filter(section_code=section, is_active=True).order_by('id').first()
        if not service:
            raise CommandError(f'Không có dịch vụ active cho {section}')
        services[section] = service

    core_areas = list(Area.objects.filter(ward_code__in=['27568', '26890']))
    if len(core_areas) != 2:
        raise CommandError('Thiếu Area 27568 / 26890')
    neighbor_areas = list(
        Area.objects.filter(province_code='79')
        .exclude(ward_code__in=['27568', '26890'])
        .order_by('ward_code')[:6]
    )
    work_areas = core_areas + neighbor_areas

    def make_user(phone, name, gender, role):
        data = {
            'username': phone,
            'email': f'{phone}@demo.cleanwise.vn',
            'role': role,
            'is_active': True,
            'password': password,
            'phone_number': phone,
            'first_name': name,
            'last_name': '',
            'gender': gender_value(User, gender),
        }
        user, created = User.objects.get_or_create(username=phone, defaults=data)
        if not created:
            for key, value in data.items():
                setattr(user, key, value)
            user.save()
        return user

    customers = [make_user(phone, name, gender, role_customer) for phone, name, gender in CUSTOMERS]
    workers = [make_user(phone, name, gender, role_worker) for phone, name, gender in WORKERS]

    addresses_by_customer = {}
    for customer in customers:
        for address_data in ADDRESSES:
            has_other_default = CustomerAddress.objects.filter(
                customer=customer,
                is_default=True,
                is_active=True,
            ).exclude(label=address_data['label']).exists()
            defaults = {
                **address_data,
                'is_default': address_data['is_default'] and not has_other_default,
                'receiver_name': customer.first_name,
                'receiver_phone': customer.username,
                'city': 'Thành phố Hồ Chí Minh',
                'province_code': '79',
                'is_active': True,
            }
            address = CustomerAddress.objects.filter(
                customer=customer,
                label=address_data['label'],
            ).order_by('id').first()
            if address is None:
                address = CustomerAddress.objects.create(customer=customer, **defaults)
            else:
                for key, value in defaults.items():
                    setattr(address, key, value)
                address.save()
            addresses_by_customer.setdefault(customer.pk, []).append(address)

    missing_profiles = [
        WorkerProfile(
            user=worker,
            registered_service=services[SECTIONS[index // 2]],
            status=WorkerProfile.Status.ACTIVE,
        )
        for index, worker in enumerate(workers)
        if not WorkerProfile.objects.filter(user=worker).exists()
    ]
    if missing_profiles:
        WorkerProfile.objects.bulk_create(missing_profiles, ignore_conflicts=True)

    workers_by_section = {section: [] for section in SECTIONS}
    for index, worker in enumerate(workers):
        section = SECTIONS[index // 2]
        WorkerProfile.objects.filter(user=worker).update(
            registered_service=services[section],
            status=WorkerProfile.Status.ACTIVE,
        )
        workers_by_section[section].append(worker)
        for area in work_areas:
            WorkerWorkingArea.objects.get_or_create(worker=worker, area=area)

    command.stdout.write(
        f'Tài khoản demo: {len(customers)} customer, {len(workers)} worker; '
        f'{len(work_areas)} khu vực/worker; địa chỉ khách được giữ nguyên và cập nhật an toàn.'
    )
    return {
        'customers': customers,
        'workers': workers,
        'services': services,
        'addresses': addresses_by_customer,
        'workers_by_section': workers_by_section,
    }


def seed_media(command, demo, media_urls):
    from apps.authentication.models import User, WorkerProfile, WorkerVerificationDocument

    admin = User.objects.filter(role=User.Role.ADMIN, is_active=True).order_by('id').first()
    avatar_paths = [
        f'avatars/workers/worker_{index:02d}_{"nam" if index <= 4 else "nu"}.jpg'
        for index in range(1, 9)
    ]
    for index, (worker, relative_path) in enumerate(zip(demo['new_workers'], avatar_paths)):
        expected_gender = User.Gender.MALE if '_nam.jpg' in relative_path else User.Gender.FEMALE
        if worker.gender != expected_gender:
            raise CommandError(f'Ảnh avatar không khớp giới tính của worker {worker.username}.')
        if not worker.avatar:
            User.objects.filter(pk=worker.pk).update(avatar=media_urls[relative_path])
        profile = WorkerProfile.objects.get(user=worker)
        profile_updates = {}
        if not profile.avatar:
            profile_updates['avatar'] = media_urls[relative_path]
        if not profile.identity_number:
            profile_updates['identity_number'] = f'0792{worker.username[-8:]}'
        if not profile.bio:
            profile_updates['bio'] = BIOS[index % len(BIOS)]
        if not profile.experience_years:
            profile_updates['experience_years'] = 2 + (index % 5)
        if profile.approved_by_id is None and admin is not None:
            profile_updates['approved_by'] = admin
        if profile.approved_at is None and admin is not None:
            profile_updates['approved_at'] = timezone.now()
        if profile_updates:
            WorkerProfile.objects.filter(pk=profile.pk).update(**profile_updates)

    document_paths = (
        (WorkerVerificationDocument.DocumentType.IDENTITY_FRONT, 'worker_docs/identity_front.jpg'),
        (WorkerVerificationDocument.DocumentType.IDENTITY_BACK, 'worker_docs/identity_back.jpg'),
        (WorkerVerificationDocument.DocumentType.CERTIFICATE, 'worker_docs/certificate.jpg'),
    )
    existing_types = set(
        WorkerVerificationDocument.objects.filter(worker__in=demo['new_workers']).values_list(
            'worker_id', 'document_type',
        )
    )
    documents = []
    for worker in demo['new_workers']:
        for document_type, relative_path in document_paths:
            key = (worker.pk, document_type)
            if key not in existing_types:
                documents.append(WorkerVerificationDocument(
                    worker=worker,
                    document_type=document_type,
                    file=media_urls[relative_path],
                    file_type=WorkerVerificationDocument.FileType.IMAGE,
                    note='Tài liệu minh họa dùng cho tài khoản demo.',
                ))
                existing_types.add(key)
    if documents:
        WorkerVerificationDocument.objects.bulk_create(documents, batch_size=100)

    command.stdout.write(
        f'Ảnh Cloudinary dùng sẵn cho {len(demo["new_workers"])} worker mới; '
        f'{len(documents)} giấy tờ mới. Dry-run không upload ảnh.'
    )


def _seed_media_legacy(command, demo, media_urls):
    from apps.authentication.models import User, WorkerProfile, WorkerVerificationDocument

    admin = User.objects.filter(role='ADMIN', is_active=True).order_by('id').first()
    customer_avatar_paths = [
        f'avatars/customers/customer_{index:02d}_{"nam" if index <= 4 else "nu"}.jpg'
        for index in range(1, 9)
    ]
    worker_avatar_paths = [
        f'avatars/workers/worker_{index:02d}_{"nam" if index <= 4 else "nu"}.jpg'
        for index in range(1, 9)
    ]
    for user, relative_path in zip(demo['customers'], customer_avatar_paths):
        expected_gender = User.Gender.MALE if '_nam.jpg' in relative_path else User.Gender.FEMALE
        if user.gender != expected_gender:
            raise CommandError(f'Ảnh avatar không khớp giới tính của customer {user.username}.')
        User.objects.filter(pk=user.pk).update(avatar=media_urls[relative_path])
    for index, (user, relative_path) in enumerate(zip(demo['workers'], worker_avatar_paths)):
        expected_gender = User.Gender.MALE if '_nam.jpg' in relative_path else User.Gender.FEMALE
        if user.gender != expected_gender:
            raise CommandError(f'Ảnh avatar không khớp giới tính của worker {user.username}.')
        User.objects.filter(pk=user.pk).update(avatar=media_urls[relative_path])
        profile = WorkerProfile.objects.get(user=user)
        profile_updates = {
            'avatar': media_urls[relative_path],
            'identity_number': f'0792{user.username[-8:]}',
            'bio': BIOS[index % len(BIOS)],
            'experience_years': 2 + (index % 5),
        }
        if profile.approved_by_id is None:
            profile_updates['approved_by'] = admin
        if profile.approved_at is None and admin is not None:
            profile_updates['approved_at'] = timezone.now()
        WorkerProfile.objects.filter(user=user).update(
            **profile_updates,
        )

    document_paths = (
        (WorkerVerificationDocument.DocumentType.IDENTITY_FRONT, 'worker_docs/identity_front.jpg'),
        (WorkerVerificationDocument.DocumentType.IDENTITY_BACK, 'worker_docs/identity_back.jpg'),
        (WorkerVerificationDocument.DocumentType.CERTIFICATE, 'worker_docs/certificate.jpg'),
    )
    existing_documents = set(
        WorkerVerificationDocument.objects.filter(worker__in=demo['workers']).values_list(
            'worker_id', 'document_type', 'file',
        )
    )
    documents = []
    for worker in demo['workers']:
        for document_type, relative_path in document_paths:
            file_url = media_urls[relative_path]
            key = (worker.pk, document_type, file_url)
            if key not in existing_documents:
                documents.append(WorkerVerificationDocument(
                    worker=worker,
                    document_type=document_type,
                    file=file_url,
                    file_type=WorkerVerificationDocument.FileType.IMAGE,
                    note='Tài liệu minh họa dùng cho tài khoản demo.',
                ))
                existing_documents.add(key)
    if documents:
        WorkerVerificationDocument.objects.bulk_create(documents, batch_size=100)

    command.stdout.write(
        f'Ảnh Cloudinary: đã gắn {len(demo["customers"]) + len(demo["workers"])} avatar; '
        f'{len(documents)} giấy tờ mới. Dry-run không upload ảnh.'
    )


def _all_option_values(field):
    values = []
    for option in field.get('options', []):
        if 'when' in option:
            values.extend(item.get('value') for item in option.get('items', []))
        else:
            values.append(option.get('value'))
    return [value for value in values if value is not None]


def _options_for_field(field, values):
    options = field.get('options', [])
    if not options or 'when' not in options[0]:
        return options
    options_by = field.get('options_by')
    selected = values.get(options_by)
    for group in options:
        if group.get('when', {}).get(options_by) == selected:
            return group.get('items', [])
    return options[0].get('items', [])


def _sample_field_value(field, values, *, recurring_weekday=None, pricing_node=None):
    field_type = field.get('type')
    key = field.get('key')
    options = _options_for_field(field, values)

    if field_type == 'DATE':
        return timezone.localdate().isoformat()
    if field_type == 'TIME':
        return '10:00'
    if field_type == 'SINGLE_SELECT':
        available = [option.get('value') for option in options]
        if pricing_node is not None and isinstance(pricing_node, dict):
            match = next((value for value in pricing_node if value in available), None)
            if match is not None:
                return match
        if key == 'duration':
            return '2_HOURS' if '2_HOURS' in available else (available[0] if available else None)
        if key == 'package_duration':
            return '1_MONTH' if '1_MONTH' in available else (available[0] if available else None)
        return available[0] if available else None
    if field_type == 'MULTI_SELECT':
        if not field.get('required'):
            return []
        return [options[0]['value']] if options else []
    if field_type == 'WEEKDAY_MULTI_SELECT':
        if recurring_weekday is not None and recurring_weekday in _all_option_values(field):
            return [recurring_weekday]
        min_selections = max(field.get('min_selections', 1), 1)
        return _all_option_values(field)[:min_selections]
    if field_type == 'QUANTITY':
        return max(int(field.get('min', 1)), 1)
    if field_type == 'BOOLEAN':
        return False
    if field_type in ('TEXT', 'TEXTAREA'):
        return 'Ưu tiên làm kỹ các khu vực thường sử dụng.' if field.get('required') else ''
    if field_type == 'REPEATABLE_GROUP':
        item_fields = field.get('item_fields', [])
        min_items = field.get('min_items', 0)
        count = max(min_items, 1 if pricing_node else 0)
        items = []
        for _ in range(count):
            item = {}
            node = pricing_node
            for subfield in item_fields:
                child_node = node if isinstance(node, dict) else None
                item[subfield['key']] = _sample_field_value(
                    subfield,
                    item,
                    pricing_node=child_node,
                )
                if isinstance(node, dict):
                    node = node.get(item[subfield['key']])
            items.append(item)
        return items
    return None


def _select_price_option(fields, service_data, keys, excluded=None):
    excluded = excluded or set()
    for field in fields:
        if field.get('key') in excluded:
            continue
        matches = [value for value in _all_option_values(field) if value in keys]
        if matches:
            service_data[field['key']] = matches[0]
            return field
    return None


def _build_service_data(service, *, date_value, start_time, recurring_weekday):
    from apps.bookings.booking_service import calculate_booking_price
    from apps.bookings.service_data_validation import validate_service_data

    schema = service.form_schema or {}
    fields = schema.get('fields', [])
    pricing = service.pricing_config or {}
    service_data = {}

    for field in fields:
        key = field.get('key')
        if not key:
            continue
        value = _sample_field_value(
            field,
            service_data,
            recurring_weekday=recurring_weekday,
            pricing_node=pricing.get('unit_prices') if field.get('type') == 'REPEATABLE_GROUP' else None,
        )
        if value is not None:
            service_data[key] = value
    if 'date' in {field.get('key') for field in fields}:
        service_data['date'] = date_value.isoformat()
    if 'start_time' in {field.get('key') for field in fields}:
        service_data['start_time'] = start_time

    base_prices = pricing.get('base_prices')
    if isinstance(base_prices, dict):
        _select_price_option(fields, service_data, set(base_prices))

    price_matrix = pricing.get('price_matrix')
    if isinstance(price_matrix, dict) and price_matrix:
        outer = _select_price_option(fields, service_data, set(price_matrix))
        if outer:
            outer_value = service_data[outer['key']]
            inner_map = price_matrix.get(outer_value, {})
            if isinstance(inner_map, dict) and inner_map:
                _select_price_option(
                    fields,
                    service_data,
                    set(inner_map),
                    excluded={outer['key']},
                )

    unit_prices = pricing.get('unit_prices')
    if isinstance(unit_prices, dict):
        group_field = next(
            (field for field in fields if field.get('type') == 'REPEATABLE_GROUP'),
            None,
        )
        if group_field:
            items = service_data.setdefault(group_field['key'], [{}])
            if not items:
                items.append({})
            item = items[0]
            node = unit_prices
            for subfield in group_field.get('item_fields', []):
                if subfield.get('type') in ('QUANTITY', 'BOOLEAN'):
                    item.setdefault(
                        subfield['key'],
                        _sample_field_value(subfield, item),
                    )
                    continue
                if not isinstance(node, dict) or not node:
                    break
                candidate = next(
                    (value for value in _all_option_values(subfield) if value in node),
                    None,
                )
                if candidate is None:
                    candidate = next(iter(node))
                item[subfield['key']] = candidate
                node = node[candidate]

    from rest_framework.exceptions import ValidationError

    try:
        validate_service_data(schema, service_data)
    except ValidationError as exc:
        raise CommandError(
            f'Service data demo không hợp lệ cho {service.code}: {exc}'
        ) from exc
    unit_price = calculate_booking_price(service, service_data)
    if unit_price is None or unit_price <= 0:
        raise CommandError(
            f'Không tính được giá demo cho service {service.code}; '
            'cần kiểm tra form_schema/pricing_config.'
        )
    return service_data, unit_price


def _booking_state(index):
    bucket = index % 20
    if bucket < 12 or 15 <= bucket < 17:
        return 'COMPLETED'
    if bucket < 14:
        return 'CANCELLED'
    if bucket == 14:
        return 'FAILED'
    return 'ASSIGNED'


def _overlaps(start, end, intervals):
    return any(start < busy_end and end > busy_start for busy_start, busy_end in intervals)


def _allocate_worker(candidates, start, end, busy, *, step, rotation):
    if not candidates:
        raise CommandError('Không có worker phù hợp để phân công lịch demo.')
    for offset in range(730):
        candidate_start = start + step * offset
        candidate_end = end + step * offset
        ordered = candidates[rotation % len(candidates):] + candidates[:rotation % len(candidates)]
        for worker in ordered:
            intervals = busy.setdefault(worker.pk, [])
            if not _overlaps(candidate_start, candidate_end, intervals):
                intervals.append((candidate_start, candidate_end))
                return worker, candidate_start, candidate_end
    raise CommandError('Không tìm được lịch trống cho worker demo trong 2 năm.')


def _initial_busy_times(workers, *, exclude_booking_ids=None):
    from apps.worker.models import BookingAssignment

    worker_ids = [worker.pk for worker in workers]
    busy = {worker_id: [] for worker_id in worker_ids}
    accepted = BookingAssignment.objects.filter(
        worker__in=workers,
        status=BookingAssignment.Status.ACCEPTED,
    ).exclude(
        schedule__status__in=('CANCELLED', 'MISSED'),
    )
    if exclude_booking_ids:
        accepted = accepted.exclude(schedule__booking_id__in=exclude_booking_ids)
    accepted = accepted.values_list(
        'worker_id', 'schedule__scheduled_start', 'schedule__scheduled_end',
    )
    for worker_id, start, end in accepted:
        busy.setdefault(worker_id, []).append((start, end))
    return busy


def _make_schedule_plan(service, service_data, state, *, index, section_series, busy, candidates):
    from apps.bookings.schedule_builder import build_schedules

    today = timezone.localdate()
    schedule_type = (service.form_schema or {}).get('schedule_type', 'ONCE')
    recurring = schedule_type == 'RECURRING_WEEKLY'
    recurring_index = section_series[service.section_code]
    section_series[service.section_code] += 1

    if recurring:
        weekday_field = next(
            (field for field in (service.form_schema or {}).get('fields', [])
             if field.get('type') == 'WEEKDAY_MULTI_SELECT'),
            None,
        )
        weekday_values = _all_option_values(weekday_field) if weekday_field else ['MON']
        if not weekday_values:
            weekday_values = ['MON']
        weekday = weekday_values[recurring_index % len(weekday_values)]
        slot = (recurring_index // len(weekday_values)) % 2
        service_data['weekdays'] = [weekday]
        service_data['package_duration'] = '1_MONTH'
        if '1_MONTH' not in _all_option_values(
            next((field for field in (service.form_schema or {}).get('fields', [])
                  if field.get('key') == 'package_duration'), {})
        ):
            package_field = next(
                (field for field in (service.form_schema or {}).get('fields', [])
                 if field.get('key') == 'package_duration'),
                None,
            )
            package_options = _all_option_values(package_field) if package_field else []
            if package_options:
                service_data['package_duration'] = package_options[0]
        service_data['start_time'] = '08:00' if slot == 0 else '13:00'

    if state == 'COMPLETED':
        target_day = today - timedelta(days=30 + ((index * 37) % 300))
    elif state == 'FAILED':
        target_day = today - timedelta(days=2 + (index // 16))
    elif state == 'CANCELLED':
        target_day = today + timedelta(days=3 + (index // 16))
    else:
        target_day = today + timedelta(days=3 + (index // 16))

    if recurring:
        weekday_index = {'MON': 0, 'TUE': 1, 'WED': 2, 'THU': 3, 'FRI': 4, 'SAT': 5, 'SUN': 6}
        wanted_weekday = weekday_index.get(service_data['weekdays'][0], 0)
        if state in ('COMPLETED', 'FAILED'):
            target_day = today - timedelta(days=35 + (recurring_index // 14) * 35)
        elif state in ('PENDING', 'ASSIGNED', 'CANCELLED'):
            target_day = today + timedelta(days=7 + (recurring_index // 14) * 35)
        target_day += timedelta(days=(wanted_weekday - target_day.weekday()) % 7)

    if any(field.get('key') == 'date' for field in (service.form_schema or {}).get('fields', [])):
        service_data['date'] = target_day.isoformat()
    if 'start_time' not in service_data:
        slot = (index // 8) % 2
        service_data['start_time'] = '08:00' if slot == 0 else '13:00'

    raw_schedules = build_schedules(service.form_schema or {}, service_data)
    if recurring:
        raw_first_day = raw_schedules[0]['scheduled_start'].date()
        shift = target_day - raw_first_day
        raw_schedules = [
            {
                'scheduled_start': item['scheduled_start'] + timedelta(days=shift.days),
                'scheduled_end': item['scheduled_end'] + timedelta(days=shift.days),
            }
            for item in raw_schedules
        ]

    rows = []
    for sequence, item in enumerate(raw_schedules, start=1):
        start = item['scheduled_start']
        end = item['scheduled_end']
        assigned_worker = None
        if state in ('COMPLETED', 'ASSIGNED'):
            assigned_worker, start, end = _allocate_worker(
                candidates,
                start,
                end,
                busy,
                step=timedelta(days=7 if recurring else 1),
                rotation=index + sequence,
            )

        if state == 'COMPLETED':
            schedule_status = 'COMPLETED'
            actual_start, actual_end = start, end
        elif state == 'CANCELLED':
            schedule_status = 'CANCELLED'
            actual_start = actual_end = None
        elif state == 'FAILED':
            schedule_status = 'MISSED'
            actual_start = actual_end = None
        else:
            schedule_status = 'PENDING'
            actual_start = actual_end = None

        rows.append({
            'sequence_no': sequence,
            'scheduled_start': start,
            'scheduled_end': end,
            'status': schedule_status,
            'actual_start': actual_start,
            'actual_end': actual_end,
            'worker': assigned_worker,
            'note': (
                'Lịch demo được tạo tự động.'
                if sequence == 1 else 'Buổi định kỳ trong gói dịch vụ demo.'
            ),
        })
    if not rows:
        raise CommandError(f'Không sinh được lịch cho {service.code}')
    return rows, service_data


def _booking_price(service, service_data, unit_price, session_count):
    from apps.bookings.booking_service import get_package_discount_percent

    if (service.pricing_config or {}).get('pricing_unit') == 'PER_SESSION':
        package_discount = get_package_discount_percent(service, service_data)
        subtotal = (unit_price * session_count * (Decimal('1') - package_discount / Decimal('100')))
        subtotal = subtotal.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        effective_unit_price = (subtotal / session_count).quantize(
            Decimal('0.01'), rounding=ROUND_HALF_UP,
        )
    else:
        package_discount = Decimal('0')
        subtotal = unit_price.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        effective_unit_price = None

    return subtotal, effective_unit_price, package_discount


def seed_new_worker_availability(command, demo):
    from apps.worker.models import WorkerAvailability

    availability_rows = []
    for worker in demo['new_workers']:
        existing = set(
            WorkerAvailability.objects.filter(worker=worker, is_active=True).values_list(
                'weekday', 'start_time', 'end_time',
            )
        )
        for weekday in range(7):
            start_time = time(8, 0)
            end_time = time(18, 0)
            if (weekday, start_time, end_time) not in existing:
                availability_rows.append(WorkerAvailability(
                    worker=worker,
                    weekday=weekday,
                    start_time=start_time,
                    end_time=end_time,
                    is_active=True,
                ))
    if availability_rows:
        WorkerAvailability.objects.bulk_create(availability_rows, batch_size=100)
    command.stdout.write(
        f'Lịch làm việc: thêm {len(availability_rows)} khung giờ cho 8 worker mới.'
    )


@transaction.atomic
def seed_new_worker_bookings(command, demo):
    from apps.authentication.models import User
    from apps.bookings.models import Booking, BookingActivity, BookingSchedule
    from apps.bookings.booking_service import _generate_booking_code, calculate_booking_price
    from apps.bookings.service_data_validation import validate_service_data
    from apps.payments.models import Payment
    from apps.worker.models import BookingAssignment, WorkerAvailability, WorkerWorkingArea

    home_service = demo['services']['HOME_CLEANING']
    expected_seed_keys = {}
    order_index_by_key = {}
    position_by_seed_key = {}
    booking_position = 0
    for worker_index, worker in enumerate(demo['new_workers'], start=1):
        for order_index in range(1, NEW_WORKER_BOOKINGS_PER_ACCOUNT + 1):
            seed_key = new_worker_seed_key(worker_index, order_index)
            expected_seed_keys[seed_key] = worker
            order_index_by_key[seed_key] = order_index
            position_by_seed_key[seed_key] = booking_position
            booking_position += 1
    list(
        User.objects.select_for_update()
        .filter(pk__in=[worker.pk for worker in demo['new_workers']])
        .order_by('pk')
        .values_list('pk', flat=True)
    )
    existing_bookings_by_seed_key = {}
    for activity in BookingActivity.objects.filter(
        metadata__seed_key__in=expected_seed_keys,
        event_type=BookingActivity.EventType.BOOKING_CREATED,
    ).select_related('booking'):
        seed_key = activity.metadata.get('seed_key')
        if seed_key in existing_bookings_by_seed_key:
            raise CommandError(f'Tìm thấy nhiều BookingActivity cho seed_key {seed_key}.')
        existing_bookings_by_seed_key[seed_key] = activity.booking

    busy = _initial_busy_times(demo['workers'])
    section_series = {section: 0 for section in SECTIONS}
    new_bookings = []
    planned_rows = {}
    new_codes_by_seed_key = {}
    generated_codes = set()
    for seed_key, worker in expected_seed_keys.items():
        if seed_key in existing_bookings_by_seed_key:
            continue
        index = position_by_seed_key[seed_key]
        booking_state = (
            Booking.Status.COMPLETED
            if order_index_by_key[seed_key] == 1
            else Booking.Status.ASSIGNED
        )
        code = _generate_booking_code()
        while code in generated_codes:
            code = _generate_booking_code()
        generated_codes.add(code)
        customer = demo['customers'][index % len(demo['customers'])]
        customer_addresses = demo['addresses'][customer.pk]
        address_count = (home_service.form_schema or {}).get('address_count', 1)
        if address_count >= 2 and len(customer_addresses) < 2:
            raise CommandError(
                f'Booking dịch vụ dọn nhà cần hai địa chỉ nhưng {customer.username} chưa đủ địa chỉ.'
            )
        service_data, unit_price = _build_service_data(
            home_service,
            date_value=timezone.localdate(),
            start_time='08:00' if index % 2 == 0 else '13:00',
            recurring_weekday=('MON', 'TUE', 'WED', 'THU', 'FRI', 'SAT', 'SUN')[
                section_series['HOME_CLEANING'] % 7
            ],
        )
        schedule_rows, service_data = _make_schedule_plan(
            home_service,
            service_data,
            booking_state,
            index=DEMO_BOOKING_COUNT + index + 1,
            section_series=section_series,
            busy=busy,
            candidates=[worker],
        )
        validate_service_data(home_service.form_schema or {}, service_data)
        unit_price = calculate_booking_price(home_service, service_data)
        if unit_price is None or unit_price <= 0:
            raise CommandError(f'Không tính được giá demo cho service {home_service.code}.')
        subtotal, effective_unit_price, package_discount = _booking_price(
            home_service,
            service_data,
            unit_price,
            len(schedule_rows),
        )
        delivery_address = customer_addresses[1] if address_count >= 2 else None
        booking = Booking(
            booking_code=code,
            customer=customer,
            service=home_service,
            service_data=service_data,
            address=customer_addresses[0],
            delivery_address=delivery_address,
            note='Khách ưu tiên vệ sinh kỹ khu vực sinh hoạt chung và nhà bếp.',
            status=booking_state,
            payment_status=Booking.PaymentStatus.PAID,
            price_breakdown={
                'unit_price': (
                    str(effective_unit_price)
                    if effective_unit_price is not None else None
                ),
                'base_unit_price': str(unit_price),
                'sessions_count': len(schedule_rows),
                'package_discount_percent': str(package_discount),
                'subtotal_amount': str(subtotal),
                'discount_amount': '0.00',
                'total_amount': str(subtotal),
                'pricing_config_snapshot': home_service.pricing_config,
                'voucher': None,
            },
            subtotal_amount=subtotal,
            discount_amount=Decimal('0.00'),
            total_amount=subtotal,
        )
        new_bookings.append(booking)
        planned_rows[seed_key] = schedule_rows
        new_codes_by_seed_key[seed_key] = code
    if new_bookings:
        Booking.objects.bulk_create(new_bookings, batch_size=100)

    bookings_by_code = {
        booking.booking_code: booking
        for booking in Booking.objects.filter(
            booking_code__in=new_codes_by_seed_key.values(),
        ).select_related(
            'customer', 'service', 'address',
        )
    }
    if len(bookings_by_code) != len(new_codes_by_seed_key):
        raise CommandError(
            f'Đã tạo {len(bookings_by_code)} booking mới, cần đúng {len(new_codes_by_seed_key)}.'
        )
    bookings_by_seed_key = dict(existing_bookings_by_seed_key)
    for seed_key, code in new_codes_by_seed_key.items():
        bookings_by_seed_key[seed_key] = bookings_by_code[code]

    seed_activities = []
    for seed_key, code in new_codes_by_seed_key.items():
        booking = bookings_by_code[code]
        seed_activities.append(BookingActivity(
            booking=booking,
            actor=booking.customer,
            event_type=BookingActivity.EventType.BOOKING_CREATED,
            message=f'Khách hàng tạo booking demo {booking.booking_code}.',
            new_data={
                'customer_id': booking.customer_id,
                'service_id': booking.service_id,
            },
            metadata={'seed_key': seed_key},
        ))
    if seed_activities:
        BookingActivity.objects.bulk_create(seed_activities, batch_size=100)

    new_schedules = []
    for seed_key, rows in planned_rows.items():
        booking = bookings_by_seed_key[seed_key]
        for row in rows:
            new_schedules.append(BookingSchedule(
                booking=booking,
                sequence_no=row['sequence_no'],
                scheduled_start=row['scheduled_start'],
                scheduled_end=row['scheduled_end'],
                status=row['status'],
                actual_start=row['actual_start'],
                actual_end=row['actual_end'],
                note=row['note'],
            ))
    if new_schedules:
        BookingSchedule.objects.bulk_create(new_schedules, batch_size=500)

    schedules_by_booking = {}
    for schedule in BookingSchedule.objects.filter(
        booking_id__in=[booking.pk for booking in bookings_by_seed_key.values()],
    ).select_related('booking').order_by('booking__booking_code', 'sequence_no'):
        schedules_by_booking.setdefault(schedule.booking_id, []).append(schedule)

    for seed_key, worker in expected_seed_keys.items():
        if order_index_by_key[seed_key] != 1:
            continue
        booking = bookings_by_seed_key[seed_key]
        booking_schedules = schedules_by_booking.get(booking.pk, [])
        if booking.status == Booking.Status.COMPLETED:
            if any(
                schedule.status != BookingSchedule.Status.COMPLETED
                for schedule in booking_schedules
            ):
                raise CommandError(f'{booking.booking_code} có trạng thái hoàn thành không đồng bộ.')
            continue
        if (
            booking.status != Booking.Status.ASSIGNED
            or not booking_schedules
            or any(
                schedule.status != BookingSchedule.Status.PENDING
                for schedule in booking_schedules
            )
        ):
            raise CommandError(
                f'{booking.booking_code} không thể chuyển sang lịch hoàn thành an toàn.'
            )
        service_data = json.loads(json.dumps(booking.service_data))
        rows, service_data = _make_schedule_plan(
            home_service,
            service_data,
            'COMPLETED',
            index=DEMO_BOOKING_COUNT + position_by_seed_key[seed_key] + 1,
            section_series=section_series,
            busy=busy,
            candidates=[worker],
        )
        if len(rows) != len(booking_schedules):
            raise CommandError(f'{booking.booking_code} có số schedule không khớp.')
        for schedule, row in zip(booking_schedules, rows):
            schedule.scheduled_start = row['scheduled_start']
            schedule.scheduled_end = row['scheduled_end']
            schedule.actual_start = row['actual_start']
            schedule.actual_end = row['actual_end']
            schedule.status = row['status']
            schedule.note = row['note']
        BookingSchedule.objects.bulk_update(
            booking_schedules,
            ['scheduled_start', 'scheduled_end', 'actual_start', 'actual_end', 'status', 'note'],
        )
        booking.status = Booking.Status.COMPLETED
        booking.service_data = service_data
        Booking.objects.filter(pk=booking.pk).update(
            status=booking.status,
            service_data=service_data,
        )

    admin = User.objects.filter(role=User.Role.ADMIN, is_active=True).order_by('id').first()
    customer_ids = {customer.pk for customer in demo['customers']}
    worker_area_codes = {}
    for worker_id, ward_code in WorkerWorkingArea.objects.filter(
        worker__in=demo['new_workers'],
    ).values_list('worker_id', 'area__ward_code'):
        worker_area_codes.setdefault(worker_id, set()).add(ward_code)
    availability_by_worker = {}
    for availability in WorkerAvailability.objects.filter(
        worker__in=demo['new_workers'],
        is_active=True,
    ):
        availability_by_worker.setdefault(availability.worker_id, []).append(availability)
    existing_assignments = {
        assignment.schedule_id: assignment
        for assignment in BookingAssignment.objects.filter(
            schedule__booking_id__in=[
                booking.pk for booking in bookings_by_seed_key.values()
            ],
            status=BookingAssignment.Status.ACCEPTED,
        )
    }
    new_assignments = []
    for seed_key, worker in expected_seed_keys.items():
        booking = bookings_by_seed_key[seed_key]
        completed_booking = order_index_by_key[seed_key] == 1
        expected_booking_status = (
            Booking.Status.COMPLETED if completed_booking else Booking.Status.ASSIGNED
        )
        expected_schedule_status = (
            BookingSchedule.Status.COMPLETED
            if completed_booking else BookingSchedule.Status.PENDING
        )
        code = booking.booking_code
        if booking.service_id != home_service.pk or booking.customer_id not in customer_ids:
            raise CommandError(f'{code} không gắn đúng customer hoặc dịch vụ dọn nhà.')
        if booking.address.ward_code not in worker_area_codes.get(worker.pk, set()):
            raise CommandError(f'{code} nằm ngoài khu vực hoạt động của {worker.username}.')
        if (
            booking.status != expected_booking_status
            or booking.payment_status != Booking.PaymentStatus.PAID
        ):
            raise CommandError(f'{code} có trạng thái booking/thanh toán không đồng bộ.')
        booking_schedules = schedules_by_booking.get(booking.pk, [])
        if not booking_schedules:
            raise CommandError(f'{code} chưa có BookingSchedule.')
        for schedule in booking_schedules:
            if schedule.status != expected_schedule_status:
                raise CommandError(f'{code} có lịch không khớp trạng thái seed.')
            local_start = timezone.localtime(schedule.scheduled_start)
            local_end = timezone.localtime(schedule.scheduled_end)
            start_time = local_start.time().replace(tzinfo=None)
            end_time = local_end.time().replace(tzinfo=None)
            fits_availability = any(
                row.weekday == local_start.weekday()
                and row.start_time <= start_time
                and row.end_time >= end_time
                for row in availability_by_worker.get(worker.pk, [])
            )
            if not fits_availability:
                raise CommandError(
                    f'{code} có lịch ngoài giờ làm việc đã khai báo của {worker.username}.'
                )
            assignment = existing_assignments.get(schedule.pk)
            if assignment:
                if assignment.worker_id != worker.pk:
                    raise CommandError(f'{code} đã được gán cho worker khác; không tự phân công lại.')
                continue
            new_assignments.append(BookingAssignment(
                schedule=schedule,
                worker=worker,
                assigned_by=admin,
                assigned_method=BookingAssignment.AssignedMethod.MANUAL,
                status=BookingAssignment.Status.ACCEPTED,
                response_note='Nhân viên đã xác nhận lịch dọn nhà demo.',
                responded_at=timezone.now(),
            ))
    if new_assignments:
        BookingAssignment.objects.bulk_create(new_assignments, batch_size=500)

    existing_payments = {
        payment.booking_id: payment
        for payment in Payment.objects.filter(
            booking_id__in=[booking.pk for booking in bookings_by_seed_key.values()],
        )
    }
    new_payments = []
    for booking in bookings_by_seed_key.values():
        code = booking.booking_code
        payment = existing_payments.get(booking.pk)
        if payment:
            if (
                payment.customer_id != booking.customer_id
                or payment.amount != booking.total_amount
                or payment.status != Payment.Status.SUCCESS
            ):
                raise CommandError(f'{code} có payment hiện tại không đồng bộ; không cập nhật payment.')
            continue
        new_payments.append(Payment(
            customer=booking.customer,
            booking=booking,
            amount=booking.total_amount,
            method=Payment.Method.BANK_TRANSFER,
            status=Payment.Status.SUCCESS,
            transaction_code=f'DEMO-TXN-{code}',
            paid_at=timezone.now(),
        ))
    if new_payments:
        Payment.objects.bulk_create(new_payments, batch_size=500)

    base_marker = BookingActivity.objects.filter(
        metadata__seed_key=base_booking_seed_key(1),
        event_type=BookingActivity.EventType.BOOKING_CREATED,
    ).order_by('id').first()
    date_anchor = base_marker.created_at if base_marker else timezone.now()
    for index, booking in enumerate(bookings_by_seed_key.values(), start=1):
        booking_schedules = schedules_by_booking.get(booking.pk, [])
        if booking.status == Booking.Status.COMPLETED and booking_schedules:
            created_at = min(
                schedule.actual_start or schedule.scheduled_start
                for schedule in booking_schedules
            ) - timedelta(days=7)
        else:
            created_at = date_anchor - timedelta(days=1 + ((index * 13) % 30))
        Booking.objects.filter(pk=booking.pk).update(created_at=created_at)
        booking.created_at = created_at

    total_schedules = sum(len(rows) for rows in schedules_by_booking.values())
    bookings = {
        booking.booking_code: booking
        for booking in bookings_by_seed_key.values()
    }
    command.stdout.write(
        f'Booking worker mới: {len(new_bookings)} mới, hiện có {len(bookings)}; '
        f'{total_schedules} schedule, {len(new_assignments)} assignment, '
        f'{len(new_payments)} payment, {len(seed_activities)} seed_key activity mới.'
    )
    return bookings, schedules_by_booking


def _replace_legacy_booking_code(booking, new_code):
    from apps.bookings.models import Booking, BookingActivity
    from apps.notifications.models import Notification
    from apps.payments.models import Payment
    from apps.wallets.models import WalletTransaction

    old_code = booking.booking_code
    if Booking.objects.exclude(pk=booking.pk).filter(booking_code=new_code).exists():
        raise CommandError(f'Mã booking {new_code} đã tồn tại; không thể đổi mã {old_code}.')
    Booking.objects.filter(pk=booking.pk).update(booking_code=new_code)
    booking.booking_code = new_code

    for payment in Payment.objects.filter(booking=booking):
        if payment.transaction_code and old_code in payment.transaction_code:
            payment.transaction_code = payment.transaction_code.replace(old_code, new_code)
            payment.save(update_fields=['transaction_code', 'updated_at'])
    for wallet_tx in WalletTransaction.objects.filter(booking=booking):
        updates = {}
        if wallet_tx.idempotency_key and old_code in wallet_tx.idempotency_key:
            updates['idempotency_key'] = wallet_tx.idempotency_key.replace(old_code, new_code)
        if wallet_tx.note and old_code in wallet_tx.note:
            updates['note'] = wallet_tx.note.replace(old_code, new_code)
        if updates:
            WalletTransaction.objects.filter(pk=wallet_tx.pk).update(**updates)
    for notification in Notification.objects.filter(related_booking=booking):
        if old_code in notification.message:
            Notification.objects.filter(pk=notification.pk).update(
                message=notification.message.replace(old_code, new_code),
            )
    for activity in BookingActivity.objects.filter(booking=booking):
        if old_code in activity.message:
            BookingActivity.objects.filter(pk=activity.pk).update(
                message=activity.message.replace(old_code, new_code),
            )


def _spread_completed_demo_schedules(demo, bookings_by_key, schedules_by_booking):
    from django.utils import timezone

    from apps.worker.models import BookingAssignment
    from apps.wallets.models import WorkerEarning

    completed_base_ids = [
        booking.pk
        for booking in bookings_by_key.values()
        if booking.status == 'COMPLETED'
    ]
    busy = _initial_busy_times(
        demo['workers'],
        exclude_booking_ids=completed_base_ids,
    )
    accepted_workers = {
        assignment.schedule_id: assignment.worker
        for assignment in BookingAssignment.objects.filter(
            schedule__booking_id__in=demo_booking_ids(),
            status=BookingAssignment.Status.ACCEPTED,
        ).select_related('worker')
    }
    today = timezone.localdate()
    days_elapsed = (today - today.replace(month=1, day=1)).days
    maximum_age = min(350, max(35, days_elapsed - 14))
    worker_by_id = {worker.pk: worker for worker in demo['workers']}
    changed_schedules = []

    for index in range(1, DEMO_BOOKING_COUNT + 1):
        booking = bookings_by_key[base_booking_seed_key(index)]
        if booking.status != 'COMPLETED':
            continue
        schedules = schedules_by_booking.get(booking.pk, [])
        if not schedules:
            raise CommandError(f'{booking.booking_code} không có lịch hoàn thành để phân bổ ngày.')
        age_range = max(1, maximum_age - 34)
        first_day = today - timedelta(days=35 + ((index * 37) % age_range))
        first_schedule = schedules[0]
        original_local = timezone.localtime(first_schedule.scheduled_start)
        first_day += timedelta(
            days=(original_local.weekday() - first_day.weekday()) % 7,
        )
        recurring = len(schedules) > 1

        for schedule in schedules:
            worker = accepted_workers.get(schedule.pk)
            if worker is None or worker.pk not in worker_by_id:
                raise CommandError(
                    f'{booking.booking_code} có lịch hoàn thành chưa được phân công worker.'
                )
            local_start = timezone.localtime(schedule.scheduled_start)
            session_offset = 7 * (schedule.sequence_no - 1) if recurring else 0
            target_day = first_day + timedelta(days=session_offset)
            target_start = timezone.make_aware(
                datetime.combine(
                    target_day,
                    local_start.time().replace(tzinfo=None),
                ),
                timezone.get_current_timezone(),
            )
            duration = schedule.scheduled_end - schedule.scheduled_start
            _, start, end = _allocate_worker(
                [worker_by_id[worker.pk]],
                target_start,
                target_start + duration,
                busy,
                step=timedelta(days=7 if recurring else 1),
                rotation=index + schedule.sequence_no,
            )
            schedule.scheduled_start = start
            schedule.scheduled_end = end
            schedule.actual_start = start
            schedule.actual_end = end
            changed_schedules.append(schedule)

    if changed_schedules:
        from apps.bookings.models import BookingSchedule

        BookingSchedule.objects.bulk_update(
            changed_schedules,
            ['scheduled_start', 'scheduled_end', 'actual_start', 'actual_end'],
            batch_size=500,
        )
        for schedule in changed_schedules:
            WorkerEarning.objects.filter(schedule_id=schedule.pk).update(
                completed_at=schedule.actual_end,
            )
        from apps.payments.models import Payment

        updated_booking_ids = {
            schedule.booking_id for schedule in changed_schedules
        }
        for booking in bookings_by_key.values():
            if booking.pk not in updated_booking_ids:
                continue
            completed_at = max(
                schedule.actual_end for schedule in changed_schedules
                if schedule.booking_id == booking.pk
            )
            Payment.objects.filter(
                booking=booking,
                status='SUCCESS',
            ).update(paid_at=completed_at)


@transaction.atomic
def seed_bookings(command, demo, media_urls):
    from django.contrib.auth import get_user_model

    from apps.bookings.models import Booking, BookingActivity, BookingSchedule
    from apps.bookings.booking_service import _generate_booking_code
    from apps.payments.models import Payment
    from apps.worker.models import BookingAssignment

    User = get_user_model()
    expected_seed_keys = {
        base_booking_seed_key(index)
        for index in range(1, DEMO_BOOKING_COUNT + 1)
    }
    activity_by_key = {}
    for activity in BookingActivity.objects.filter(
        metadata__seed_key__in=expected_seed_keys,
        event_type=BookingActivity.EventType.BOOKING_CREATED,
    ).select_related('booking'):
        key = activity.metadata.get('seed_key')
        if key in activity_by_key:
            raise CommandError(f'Tìm thấy nhiều BookingActivity cho seed_key {key}.')
        activity_by_key[key] = activity

    legacy_by_index = {}
    for booking in Booking.objects.filter(
        booking_code__startswith=DEMO_BOOKING_PREFIX,
    ).select_related('customer', 'service', 'address', 'delivery_address'):
        suffix = booking.booking_code[len(DEMO_BOOKING_PREFIX):]
        if not suffix.isdigit() or not 1 <= int(suffix) <= DEMO_BOOKING_COUNT:
            raise CommandError(
                f'Booking legacy {booking.booking_code} không thuộc batch 600; '
                'không thay đổi hoặc xóa dữ liệu này.'
            )
        index = int(suffix)
        if index in legacy_by_index:
            raise CommandError(f'Tìm thấy nhiều booking legacy cho vị trí {index}.')
        legacy_by_index[index] = booking

    all_addresses = demo['addresses']
    busy = _initial_busy_times(demo['workers'])
    section_series = {section: 0 for section in SECTIONS}
    bookings_by_key = {}
    planned_rows = {}
    new_bookings = []
    generated_codes = set()

    for index in range(1, DEMO_BOOKING_COUNT + 1):
        seed_key = base_booking_seed_key(index)
        activity = activity_by_key.get(seed_key)
        legacy_booking = legacy_by_index.get(index)
        if activity and legacy_booking and activity.booking_id != legacy_booking.pk:
            raise CommandError(
                f'Có cả booking đã đánh dấu và legacy ở vị trí {index}; '
                'command không xóa dữ liệu nào.'
            )
        if activity:
            booking = activity.booking
        elif legacy_booking:
            booking = legacy_booking
            code = _generate_booking_code()
            while code in generated_codes:
                code = _generate_booking_code()
            generated_codes.add(code)
            _replace_legacy_booking_code(booking, code)
        else:
            customer = demo['customers'][(index - 1) % len(demo['customers'])]
            section = SECTIONS[(index - 1) % len(SECTIONS)]
            service = demo['services'][section]
            address_choices = all_addresses[customer.pk]
            address_count = (service.form_schema or {}).get('address_count', 1)
            if address_count >= 2 and len(address_choices) < 2:
                raise CommandError(
                    f'Booking {index} cần hai địa chỉ nhưng {customer.username} chưa đủ địa chỉ.'
                )
            address = address_choices[(index // 2) % len(address_choices)]
            delivery_address = (
                address_choices[(index // 2 + 1) % len(address_choices)]
                if address_count >= 2 else None
            )
            state = _booking_state(index - 1)
            series_no = section_series[section]
            recurring_weekday = ('MON', 'WED', 'FRI', 'TUE', 'THU', 'SAT', 'SUN')[
                series_no % 7
            ]
            start_time = '08:00' if (index // 8) % 2 == 0 else '13:00'
            service_data, unit_price = _build_service_data(
                service,
                date_value=timezone.localdate(),
                start_time=start_time,
                recurring_weekday=recurring_weekday,
            )
            schedule_rows, service_data = _make_schedule_plan(
                service,
                service_data,
                state,
                index=index,
                section_series=section_series,
                busy=busy,
                candidates=_workers_for_demo_address(demo, section, address),
            )
            from apps.bookings.booking_service import calculate_booking_price
            from apps.bookings.service_data_validation import validate_service_data

            validate_service_data(service.form_schema or {}, service_data)
            unit_price = calculate_booking_price(service, service_data)
            if unit_price is None or unit_price <= 0:
                raise CommandError(f'Không tính được giá demo cho service {service.code}.')
            subtotal, effective_unit_price, package_discount = _booking_price(
                service,
                service_data,
                unit_price,
                len(schedule_rows),
            )
            payment_status = (
                'PAID' if state in ('COMPLETED', 'ASSIGNED') else 'UNPAID'
            )
            code = _generate_booking_code()
            while code in generated_codes:
                code = _generate_booking_code()
            generated_codes.add(code)
            booking = Booking(
                booking_code=code,
                customer=customer,
                service=service,
                service_data=service_data,
                address=address,
                delivery_address=delivery_address,
                note=(
                    'Vui lòng liên hệ trước khi đến.'
                    if index % 3 == 0 else 'Dữ liệu minh họa CleanWise.'
                ),
                status=state,
                payment_status=payment_status,
                price_breakdown={
                    'unit_price': (
                        str(effective_unit_price)
                        if effective_unit_price is not None else None
                    ),
                    'base_unit_price': str(unit_price),
                    'sessions_count': len(schedule_rows),
                    'package_discount_percent': str(package_discount),
                    'subtotal_amount': str(subtotal),
                    'discount_amount': '0.00',
                    'total_amount': str(subtotal),
                    'pricing_config_snapshot': service.pricing_config,
                    'voucher': None,
                },
                subtotal_amount=subtotal,
                discount_amount=Decimal('0.00'),
                total_amount=subtotal,
                cancelled_by=customer if state == 'CANCELLED' else None,
                cancelled_at=timezone.now() if state == 'CANCELLED' else None,
                cancel_reason='Khách thay đổi kế hoạch.' if state == 'CANCELLED' else None,
            )
            new_bookings.append(booking)
            planned_rows[seed_key] = schedule_rows
            bookings_by_key[seed_key] = booking
            continue

        booking.seed_demo_index = index
        bookings_by_key[seed_key] = booking

    if new_bookings:
        Booking.objects.bulk_create(new_bookings, batch_size=100)
        created_by_code = {
            booking.booking_code: booking
            for booking in Booking.objects.filter(
                booking_code__in=[row.booking_code for row in new_bookings],
            ).select_related('customer', 'service', 'address', 'delivery_address')
        }
        for seed_key, booking in list(bookings_by_key.items()):
            if booking.pk is None:
                bookings_by_key[seed_key] = created_by_code[booking.booking_code]

    if len(bookings_by_key) != DEMO_BOOKING_COUNT:
        raise CommandError(
            f'Booking demo hiện có {len(bookings_by_key)}, cần đúng {DEMO_BOOKING_COUNT}.'
        )
    for index, seed_key in enumerate(
        (base_booking_seed_key(i) for i in range(1, DEMO_BOOKING_COUNT + 1)),
        start=1,
    ):
        bookings_by_key[seed_key].seed_demo_index = index

    existing_keys = set(activity_by_key)
    seed_activities = []
    for index, seed_key in enumerate(
        (base_booking_seed_key(i) for i in range(1, DEMO_BOOKING_COUNT + 1)),
        start=1,
    ):
        if seed_key in existing_keys:
            continue
        booking = bookings_by_key[seed_key]
        seed_activities.append(BookingActivity(
            booking=booking,
            actor=booking.customer,
            event_type=BookingActivity.EventType.BOOKING_CREATED,
            message='Khách hàng tạo booking demo theo lịch sử minh họa.',
            new_data={
                'customer_id': booking.customer_id,
                'service_id': booking.service_id,
            },
            metadata={'seed_key': seed_key},
        ))
    if seed_activities:
        BookingActivity.objects.bulk_create(seed_activities, batch_size=500)

    new_schedule_rows = []
    for seed_key, rows in planned_rows.items():
        booking = bookings_by_key[seed_key]
        for row in rows:
            new_schedule_rows.append(BookingSchedule(
                booking=booking,
                sequence_no=row['sequence_no'],
                scheduled_start=row['scheduled_start'],
                scheduled_end=row['scheduled_end'],
                status=row['status'],
                actual_start=row['actual_start'],
                actual_end=row['actual_end'],
                note=row['note'],
            ))
    if new_schedule_rows:
        BookingSchedule.objects.bulk_create(new_schedule_rows, batch_size=500)

    booking_ids = [booking.pk for booking in bookings_by_key.values()]
    schedules_by_booking = {}
    for schedule in BookingSchedule.objects.filter(
        booking_id__in=booking_ids,
    ).select_related('booking').order_by('booking_id', 'sequence_no'):
        schedules_by_booking.setdefault(schedule.booking_id, []).append(schedule)

    promoted_keys = []
    for index in range(1, DEMO_BOOKING_COUNT + 1):
        if index % 20 not in (15, 16):
            continue
        seed_key = base_booking_seed_key(index)
        booking = bookings_by_key[seed_key]
        if booking.status != Booking.Status.PENDING:
            continue
        section = booking.service.section_code
        if section not in demo['workers_by_section']:
            raise CommandError(f'{booking.booking_code} có dịch vụ không hợp lệ để hoàn tất.')
        service_data = json.loads(json.dumps(booking.service_data))
        rows, service_data = _make_schedule_plan(
            booking.service,
            service_data,
            'COMPLETED',
            index=index,
            section_series=section_series,
            busy=busy,
            candidates=_workers_for_demo_address(demo, section, booking.address),
        )
        existing_schedules = schedules_by_booking.get(booking.pk, [])
        if len(rows) != len(existing_schedules):
            raise CommandError(
                f'{booking.booking_code} có số schedule không khớp; '
                'không thể nâng trạng thái an toàn.'
            )
        for schedule, row in zip(existing_schedules, rows):
            schedule.scheduled_start = row['scheduled_start']
            schedule.scheduled_end = row['scheduled_end']
            schedule.actual_start = row['actual_start']
            schedule.actual_end = row['actual_end']
            schedule.status = row['status']
            schedule.note = row['note']
        BookingSchedule.objects.bulk_update(
            existing_schedules,
            ['scheduled_start', 'scheduled_end', 'actual_start', 'actual_end', 'status', 'note'],
        )
        booking.status = Booking.Status.COMPLETED
        booking.payment_status = Booking.PaymentStatus.PAID
        booking.service_data = service_data
        Booking.objects.filter(pk=booking.pk).update(
            status=booking.status,
            payment_status=booking.payment_status,
            service_data=service_data,
        )
        planned_rows[seed_key] = rows
        promoted_keys.append(seed_key)

    admin = User.objects.filter(role=User.Role.ADMIN, is_active=True).order_by('id').first()
    accepted_by_schedule = {
        assignment.schedule_id: assignment
        for assignment in BookingAssignment.objects.filter(
            schedule__booking_id__in=booking_ids,
            status=BookingAssignment.Status.ACCEPTED,
        )
    }
    new_assignments = []
    changed_assignments = []
    for seed_key, planned in planned_rows.items():
        booking = bookings_by_key[seed_key]
        schedule_rows_by_sequence = {
            row.sequence_no: row for row in schedules_by_booking.get(booking.pk, [])
        }
        for row in planned:
            worker = row['worker']
            if worker is None:
                continue
            schedule = schedule_rows_by_sequence.get(row['sequence_no'])
            if schedule is None:
                raise CommandError(f'{booking.booking_code} thiếu schedule {row["sequence_no"]}.')
            assignment = accepted_by_schedule.get(schedule.pk)
            if assignment:
                if assignment.worker_id != worker.pk:
                    raise CommandError(
                        f'{booking.booking_code} đã có worker khác nhận lịch {schedule.sequence_no}.'
                    )
                continue
            existing = BookingAssignment.objects.filter(
                schedule=schedule,
                worker=worker,
            ).order_by('id').first()
            if existing:
                existing.status = BookingAssignment.Status.ACCEPTED
                existing.response_note = 'Nhân viên đã xác nhận lịch demo.'
                existing.responded_at = timezone.now()
                changed_assignments.append(existing)
                accepted_by_schedule[schedule.pk] = existing
            else:
                assignment = BookingAssignment(
                    schedule=schedule,
                    worker=worker,
                    assigned_by=admin,
                    assigned_method=BookingAssignment.AssignedMethod.MANUAL,
                    status=BookingAssignment.Status.ACCEPTED,
                    response_note='Nhân viên đã xác nhận lịch demo.',
                    responded_at=timezone.now(),
                )
                new_assignments.append(assignment)
                accepted_by_schedule[schedule.pk] = assignment
    if changed_assignments:
        BookingAssignment.objects.bulk_update(
            changed_assignments,
            ['status', 'response_note', 'responded_at'],
        )
    if new_assignments:
        BookingAssignment.objects.bulk_create(new_assignments, batch_size=500)

    review_promoted_bookings = 0
    review_promoted_ids = []
    assignments = list(
        BookingAssignment.objects.filter(
            schedule__booking_id__in=booking_ids,
            status=BookingAssignment.Status.ACCEPTED,
        ).select_related('worker', 'schedule', 'schedule__booking')
    )
    completed_worker_ids = {
        assignment.worker_id
        for assignment in assignments
        if assignment.schedule.status == BookingSchedule.Status.COMPLETED
    }
    for worker in demo['old_workers']:
        if worker.pk in completed_worker_ids:
            continue
        candidate = next(
            (
                assignment for assignment in assignments
                if assignment.worker_id == worker.pk
                and assignment.schedule.status == BookingSchedule.Status.PENDING
                and assignment.schedule.booking.status == Booking.Status.ASSIGNED
            ),
            None,
        )
        if candidate is not None:
            booking = candidate.schedule.booking
            booking_schedules = schedules_by_booking.get(booking.pk, [])
            booking_assignments = {
                assignment.schedule_id: assignment
                for assignment in assignments
                if assignment.schedule.booking_id == booking.pk
            }
            if (
                booking_schedules
                and all(schedule.pk in booking_assignments for schedule in booking_schedules)
                and all(
                    schedule.status == BookingSchedule.Status.PENDING
                    for schedule in booking_schedules
                )
            ):
                for schedule in booking_schedules:
                    schedule.status = BookingSchedule.Status.COMPLETED
                    schedule.actual_start = schedule.scheduled_start
                    schedule.actual_end = schedule.scheduled_end
                BookingSchedule.objects.bulk_update(
                    booking_schedules,
                    ['status', 'actual_start', 'actual_end'],
                )
                booking.status = Booking.Status.COMPLETED
                booking.payment_status = Booking.PaymentStatus.PAID
                Booking.objects.filter(pk=booking.pk).update(
                    status=booking.status,
                    payment_status=booking.payment_status,
                )
                completed_worker_ids.update(
                    assignment.worker_id for assignment in booking_assignments.values()
                )
                review_promoted_bookings += 1
                review_promoted_ids.append(booking.pk)
                continue

    existing_payments = {
        payment.booking_id: payment
        for payment in Payment.objects.filter(booking_id__in=booking_ids)
    }
    new_payments = []
    for index in range(1, DEMO_BOOKING_COUNT + 1):
        booking = bookings_by_key[base_booking_seed_key(index)]
        if booking.pk in existing_payments:
            if (
                booking.pk in {bookings_by_key[key].pk for key in promoted_keys}
                or booking.pk in review_promoted_ids
            ):
                payment = existing_payments[booking.pk]
                paid_at = max(
                    (row.actual_end for row in schedules_by_booking[booking.pk] if row.actual_end),
                    default=timezone.now(),
                )
                Payment.objects.filter(pk=payment.pk).update(
                    amount=booking.total_amount,
                    status=Payment.Status.SUCCESS,
                    transaction_code=payment.transaction_code or f'DEMO-TXN-{booking.booking_code}',
                    paid_at=paid_at,
                    failure_reason=None,
                )
            continue
        if booking.status in ('COMPLETED', 'ASSIGNED') or (
            booking.status == 'PENDING' and booking.payment_status == 'PAID'
        ):
            payment_state = Payment.Status.SUCCESS
            payment_code = f'DEMO-TXN-{booking.booking_code}'
            paid_at = (
                booking.schedules.filter(status='COMPLETED')
                .order_by('-actual_end').values_list('actual_end', flat=True).first()
                or timezone.now()
            )
        elif booking.status == 'FAILED':
            payment_state = Payment.Status.FAILED
            payment_code = None
            paid_at = None
        elif booking.status == 'CANCELLED':
            payment_state = Payment.Status.CANCELLED
            payment_code = None
            paid_at = None
        else:
            payment_state = Payment.Status.PENDING
            payment_code = None
            paid_at = None
        new_payments.append(Payment(
            customer=booking.customer,
            booking=booking,
            amount=booking.total_amount,
            method=Payment.Method.BANK_TRANSFER,
            status=payment_state,
            transaction_code=payment_code,
            paid_at=paid_at,
            failure_reason='Giao dịch demo không thành công.' if payment_state == Payment.Status.FAILED else None,
        ))
    if new_payments:
        Payment.objects.bulk_create(new_payments, batch_size=500)

    _spread_completed_demo_schedules(demo, bookings_by_key, schedules_by_booking)

    anchor_activity = BookingActivity.objects.filter(
        metadata__seed_key=base_booking_seed_key(1),
        event_type=BookingActivity.EventType.BOOKING_CREATED,
    ).order_by('id').first()
    anchor = anchor_activity.created_at if anchor_activity else timezone.now()
    for index in range(1, DEMO_BOOKING_COUNT + 1):
        booking = bookings_by_key[base_booking_seed_key(index)]
        schedules = schedules_by_booking.get(booking.pk, [])
        if booking.status == Booking.Status.COMPLETED and schedules:
            first_start = min(
                row.actual_start or row.scheduled_start for row in schedules
            )
            created_at = first_start - timedelta(days=7)
        else:
            created_at = anchor - timedelta(days=1 + ((index * 13) % 30))
        Booking.objects.filter(pk=booking.pk).update(created_at=created_at)
        booking.created_at = created_at

    bookings = {booking.booking_code: booking for booking in bookings_by_key.values()}
    if len(bookings) != DEMO_BOOKING_COUNT:
        raise CommandError('Mã booking demo bị trùng sau khi chuyển sang chuẩn CW.')
    _seed_schedule_photos(command, media_urls, schedules_by_booking)
    command.stdout.write(
        f'Booking: {len(new_bookings)} mới; '
        f'{len(promoted_keys) + review_promoted_bookings} đơn cũ được hoàn tất; '
        f'{len(bookings)} hiện có; {len(new_schedule_rows)} schedule, '
        f'{len(new_assignments)} assignment, '
        f'{len(new_payments)} payment mới.'
    )
    return bookings, schedules_by_booking


def _seed_schedule_photos(command, media_urls, schedules_by_booking):
    if not media_urls:
        return
    from apps.bookings.models import BookingScheduleImage

    existing = set(
        BookingScheduleImage.objects.filter(
            schedule__booking_id__in=demo_booking_ids(),
        ).values_list('schedule_id', 'image_type', 'image')
    )
    additions = []
    per_section_count = {}
    from apps.bookings.models import BookingSchedule

    for booking_schedules in schedules_by_booking.values():
        if not booking_schedules:
            continue
        booking = booking_schedules[0].booking
        section = booking.service.section_code
        if section not in ('HOME_CLEANING', 'APPLIANCE_CLEANING'):
            continue
        completed = next(
            (schedule for schedule in booking_schedules
             if schedule.status == BookingSchedule.Status.COMPLETED),
            None,
        )
        if completed is None:
            continue
        sequence = per_section_count.get(section, 0)
        per_section_count[section] = sequence + 1
        if sequence % 6 != 0:
            continue
        assignment = completed.assignments.filter(status='ACCEPTED').select_related('worker').first()
        if assignment is None:
            continue
        folder = f'schedule_photos/{section}'
        for image_type, filename in (
            (BookingScheduleImage.ImageType.BEFORE, 'before_01.jpg'),
            (BookingScheduleImage.ImageType.AFTER, 'after_01.jpg'),
        ):
            relative_path = f'{folder}/{filename}'
            image_url = media_urls[relative_path]
            key = (completed.pk, image_type, image_url)
            if key not in existing:
                additions.append(BookingScheduleImage(
                    uploaded_by=assignment.worker,
                    schedule=completed,
                    image_type=image_type,
                    image=image_url,
                    note='Ảnh minh họa trước/sau buổi vệ sinh demo.',
                ))
                existing.add(key)
    if additions:
        BookingScheduleImage.objects.bulk_create(additions, batch_size=100)
    command.stdout.write(f'Ảnh lịch làm: {len(additions)} ảnh mới.')


def seed_wallets_and_earnings(command, demo, bookings, schedules_by_booking):
    from apps.authentication.models import WorkerProfile
    from apps.wallets import earning_service, wallet_service
    from apps.wallets.models import Wallet, WalletTransaction, WorkerEarning
    from apps.worker.models import BookingAssignment

    users = demo['customers'] + demo['workers']
    wallets = {}
    for user in users:
        wallet, _ = Wallet.objects.get_or_create(user=user)
        wallets[user.pk] = wallet

    opening_topups = 0
    for customer in demo['customers']:
        opening_key = f'demo-customer-opening-balance:{customer.username}'
        already_credited = WalletTransaction.objects.filter(
            idempotency_key=opening_key,
        ).exists()
        wallet_service.credit_wallet(
            user=customer,
            amount=Decimal('100000'),
            type=WalletTransaction.Type.TOPUP,
            note='Số dư khởi tạo cho tài khoản demo.',
            idempotency_key=opening_key,
        )
        opening_topups += int(not already_credited)

    accepted_by_schedule = {
        assignment.schedule_id: assignment
        for assignment in BookingAssignment.objects.filter(
            schedule__booking_id__in=demo_booking_ids(),
            status=BookingAssignment.Status.ACCEPTED,
        ).select_related('worker', 'schedule__booking')
    }
    completed_schedules = [
        schedule
        for rows in schedules_by_booking.values()
        for schedule in rows
        if schedule.status == 'COMPLETED' and schedule.pk in accepted_by_schedule
    ]
    completed_schedules.sort(key=lambda schedule: (schedule.actual_end or schedule.scheduled_end, schedule.pk))

    new_earnings = 0
    new_transactions = 0
    for schedule in completed_schedules:
        booking = bookings[schedule.booking.booking_code]
        gross = earning_service.calculate_gross_amount(schedule, booking)
        commission = earning_service.calculate_commission(gross)
        worker_amount = gross - commission
        assignment = accepted_by_schedule[schedule.pk]
        earning, created = WorkerEarning.objects.get_or_create(
            schedule=schedule,
            defaults={
                'worker': assignment.worker,
                'booking': booking,
                'payment_method': WorkerEarning.PaymentMethod.ONLINE,
                'gross_amount': gross,
                'commission_rate': earning_service.COMMISSION_RATE,
                'commission_amount': commission,
                'worker_amount': worker_amount,
                'completed_at': schedule.actual_end or schedule.scheduled_end,
                'wallet_credited_at': None,
            },
        )
        new_earnings += int(created)
        transaction_key = f'demo-earning:{booking.booking_code}:{schedule.sequence_no}'
        existing_transaction = WalletTransaction.objects.filter(
            idempotency_key=transaction_key,
        ).first()
        if existing_transaction is None:
            if earning.payment_method == WorkerEarning.PaymentMethod.ONLINE and earning.worker_amount > 0:
                wallet_service.credit_wallet(
                    user=earning.worker,
                    amount=earning.worker_amount,
                    type=WalletTransaction.Type.EARNING,
                    booking=booking,
                    note=f'Thu nhập demo buổi {schedule.sequence_no} - {booking.booking_code}.',
                    idempotency_key=transaction_key,
                )
                new_transactions += 1
            earning.wallet_credited_at = timezone.now()
            earning.save(update_fields=['wallet_credited_at'])

    for worker in demo['workers']:
        completed_count = WorkerEarning.objects.filter(
            worker=worker,
            voided_at__isnull=True,
        ).count()
        WorkerProfile.objects.filter(user=worker).update(total_completed_jobs=completed_count)

    command.stdout.write(
        f'Ví: {len(wallets)}; WorkerEarning mới: {new_earnings}; '
        f'WalletTransaction thu nhập mới: {new_transactions}; '
        f'{opening_topups} lần nạp khởi tạo khách mới (100.000đ/khách, idempotent).'
    )


def seed_reviews(command, demo, media_urls):
    from django.db.models import Avg

    from apps.authentication.models import WorkerProfile
    from apps.reviews.models import Review, ReviewImage
    from apps.worker.models import BookingAssignment

    assignments = list(
        BookingAssignment.objects.filter(
            schedule__booking_id__in=demo_booking_ids(),
            schedule__status='COMPLETED',
            status=BookingAssignment.Status.ACCEPTED,
        ).select_related('schedule__booking', 'worker').order_by('schedule_id')
    )
    existing_assignment_ids = set(
        Review.objects.filter(assignment__in=assignments).values_list('assignment_id', flat=True)
    )
    reviewed_worker_ids = set(
        Review.objects.filter(
            assignment__in=assignments,
            is_visible=True,
        ).values_list('assignment__worker_id', flat=True)
    )
    selected = [
        assignment for index, assignment in enumerate(assignments)
        if index % 7 == 0 and assignment.pk not in existing_assignment_ids
    ]
    covered_workers = reviewed_worker_ids | {assignment.worker_id for assignment in selected}
    selected_ids = {assignment.pk for assignment in selected}
    workers_without_reviews = []
    for worker in demo['workers']:
        if worker.pk in covered_workers:
            continue
        assignment = next(
            (
                row for row in assignments
                if row.worker_id == worker.pk
                and row.pk not in existing_assignment_ids
                and row.pk not in selected_ids
            ),
            None,
        )
        if assignment is None:
            workers_without_reviews.append(worker.username)
            continue
        selected.append(assignment)
        selected_ids.add(assignment.pk)
        covered_workers.add(worker.pk)
    reviews = []
    assignment_by_key = {}
    for index, assignment in enumerate(selected):
        review = Review(
            assignment=assignment,
            rating=(5, 5, 4, 5, 3)[index % 5],
            comment=REVIEW_COMMENTS[index % len(REVIEW_COMMENTS)],
            is_visible=True,
        )
        reviews.append(review)
        assignment_by_key[assignment.pk] = (review, index)
    if reviews:
        Review.objects.bulk_create(reviews, batch_size=200)

    images = []
    image_paths = [f'reviews/r_{index:02d}.jpg' for index in range(1, 7)]
    for assignment in selected:
        review, index = assignment_by_key[assignment.pk]
        if index % 2 == 0:
            images.append(ReviewImage(
                review=review,
                image=media_urls[image_paths[index % len(image_paths)]],
                caption='Ảnh minh họa kết quả dịch vụ.',
            ))
    if images:
        ReviewImage.objects.bulk_create(images, batch_size=200)

    for worker in demo['workers']:
        average = Review.objects.filter(
            assignment__worker=worker,
            is_visible=True,
        ).aggregate(value=Avg('rating'))['value']
        WorkerProfile.objects.filter(user=worker).update(
            average_rating=Decimal(str(average)).quantize(Decimal('0.01'))
            if average is not None else Decimal('0.00'),
        )

    command.stdout.write(f'Review mới: {len(reviews)}; ảnh review mới: {len(images)}.')
    if workers_without_reviews:
        command.stdout.write(
            'Chưa thể tạo review vì không có lịch demo hoàn thành hợp lệ cho: '
            + ', '.join(workers_without_reviews)
        )


def seed_complaints(command, bookings, schedules_by_booking, media_urls):
    from django.contrib.auth import get_user_model

    from apps.complaints.models import (
        Complaint,
        ComplaintAttachment,
        ComplaintEvent,
        ComplaintIssueType,
    )
    from apps.worker.models import BookingAssignment
    from apps.worker.discipline_service import APPEAL_CODE

    User = get_user_model()
    admin = User.objects.filter(role='ADMIN', is_active=True).order_by('id').first()
    issue_type = ComplaintIssueType.objects.filter(
        is_active=True,
        applies_to__in=(ComplaintIssueType.AppliesTo.CUSTOMER, ComplaintIssueType.AppliesTo.ANY),
        stage__in=(ComplaintIssueType.Stage.AFTER_SERVICE, ComplaintIssueType.Stage.ANY),
    ).exclude(code=APPEAL_CODE).order_by('id').first()
    if issue_type is None:
        command.stdout.write(
            'Complaint: bỏ qua vì không có lý do phù hợp đang hoạt động; '
            'bảng lý do khiếu nại được giữ nguyên.'
        )
        return

    assignment_by_schedule = {
        assignment.schedule_id: assignment
        for assignment in BookingAssignment.objects.filter(
            schedule__booking_id__in=demo_booking_ids(),
            status=BookingAssignment.Status.ACCEPTED,
        ).select_related('worker')
    }
    existing_booking_ids = set(
        Complaint.objects.filter(
            booking_id__in=demo_booking_ids(),
        ).values_list('booking_id', flat=True)
    )
    candidates = []
    for booking in bookings.values():
        index = getattr(booking, 'seed_demo_index', None)
        if index is None:
            continue
        if booking.status != 'COMPLETED' or booking.pk in existing_booking_ids or index % 53 != 0:
            continue
        schedule = next(
            (row for row in schedules_by_booking[booking.pk] if row.status == 'COMPLETED'),
            None,
        )
        if schedule is None:
            continue
        assignment = assignment_by_schedule.get(schedule.pk)
        if assignment is None:
            continue
        candidates.append((index, booking, schedule, assignment))

    now = timezone.now()
    complaints = []
    for position, (index, booking, schedule, assignment) in enumerate(candidates):
        status_cycle = position % 4
        status = (
            Complaint.Status.PENDING,
            Complaint.Status.IN_REVIEW,
            Complaint.Status.RESOLVED,
            Complaint.Status.REJECTED,
        )[status_cycle]
        complaints.append(Complaint(
            code=f'DEMO-CMP-{index:06d}',
            booking=booking,
            schedule=schedule,
            reporter=booking.customer,
            reporter_role=Complaint.ReporterRole.CUSTOMER,
            worker=assignment.worker,
            issue_type=issue_type,
            stage=Complaint.Stage.AFTER_SERVICE,
            content=COMPLAINT_TEXTS[position % len(COMPLAINT_TEXTS)],
            status=status,
            requested_resolution=Complaint.RequestedResolution.SUPPORT,
            assigned_to=admin if status in (Complaint.Status.IN_REVIEW, Complaint.Status.RESOLVED) else None,
            assigned_at=now if status in (Complaint.Status.IN_REVIEW, Complaint.Status.RESOLVED) else None,
            resolved_by=admin if status in (Complaint.Status.RESOLVED, Complaint.Status.REJECTED) else None,
            resolution_note=(
                'Đã tiếp nhận và phản hồi khách hàng.'
                if status in (Complaint.Status.RESOLVED, Complaint.Status.REJECTED) else None
            ),
            resolved_at=now if status in (Complaint.Status.RESOLVED, Complaint.Status.REJECTED) else None,
        ))
    if complaints:
        Complaint.objects.bulk_create(complaints, batch_size=100)
    saved_complaints = list(
        Complaint.objects.filter(
            booking_id__in=demo_booking_ids(),
        ).select_related('booking').order_by('id')
    )
    existing_events = set(
        ComplaintEvent.objects.filter(complaint__in=saved_complaints)
        .values_list('complaint_id', 'kind')
    )
    events = []
    for complaint in saved_complaints:
        key = (complaint.pk, ComplaintEvent.Kind.CLAIM)
        if key not in existing_events:
            events.append(ComplaintEvent(
                complaint=complaint,
                actor=complaint.reporter,
                kind=ComplaintEvent.Kind.CLAIM,
                message='CleanWise đã tiếp nhận phản ánh demo.',
                is_public=True,
            ))
            existing_events.add(key)
        if complaint.status in (Complaint.Status.RESOLVED, Complaint.Status.REJECTED):
            key = (complaint.pk, ComplaintEvent.Kind.CLOSE)
            if key not in existing_events:
                events.append(ComplaintEvent(
                    complaint=complaint,
                    actor=admin or complaint.reporter,
                    kind=ComplaintEvent.Kind.CLOSE,
                    message=complaint.resolution_note or 'Đã cập nhật kết quả xử lý.',
                    is_public=True,
                ))
                existing_events.add(key)
    if events:
        ComplaintEvent.objects.bulk_create(events, batch_size=100)

    existing_attachments = set(
        ComplaintAttachment.objects.filter(complaint__in=saved_complaints)
        .values_list('complaint_id', 'file')
    )
    attachments = []
    complaint_paths = [f'complaints/c_{index:02d}.jpg' for index in range(1, 9)]
    for index, complaint in enumerate(saved_complaints):
        if index % 2:
            continue
        file_url = media_urls[complaint_paths[index % len(complaint_paths)]]
        if (complaint.pk, file_url) not in existing_attachments:
            attachments.append(ComplaintAttachment(
                complaint=complaint,
                file=file_url,
                public_id='',
                file_type='image/jpeg',
            ))
    if attachments:
        ComplaintAttachment.objects.bulk_create(attachments, batch_size=100)

    command.stdout.write(
        f'Complaint: {len(complaints)} mới; {len(events)} sự kiện; '
        f'{len(attachments)} ảnh đính kèm mới.'
    )


def seed_notifications(command, demo, bookings):
    from apps.complaints.models import Complaint
    from apps.notifications.models import Notification
    from apps.payments.models import Payment
    from apps.worker.models import BookingAssignment

    booking_ids = [booking.pk for booking in bookings.values()]
    existing_keys = set(
        Notification.objects.filter(related_booking_id__in=booking_ids)
        .values_list('user_id', 'related_booking_id', 'type', 'target')
    )
    demo_users = demo['customers'] + demo['workers']
    existing_notification_user_ids = set(
        Notification.objects.filter(
            user__in=demo_users,
        ).values_list('user_id', flat=True)
    )
    payments_by_booking = {}
    for payment in Payment.objects.filter(
        booking_id__in=booking_ids,
    ).order_by('id'):
        payments_by_booking.setdefault(payment.booking_id, payment)
    assignments_by_booking = {}
    for assignment in BookingAssignment.objects.filter(
        schedule__booking_id__in=booking_ids,
        status=BookingAssignment.Status.ACCEPTED,
    ).select_related('worker', 'worker__worker_profile', 'schedule').order_by('id'):
        assignments_by_booking.setdefault(assignment.schedule.booking_id, []).append(assignment)

    notifications = []
    for booking in bookings.values():
        if booking.status == 'COMPLETED':
            title = 'Dịch vụ đã hoàn thành'
            message = f'Đơn {booking.booking_code} đã hoàn thành. Cảm ơn bạn đã sử dụng CleanWise.'
        elif booking.status == 'CANCELLED':
            title = 'Đơn dịch vụ đã hủy'
            message = f'Đơn {booking.booking_code} đã được hủy theo yêu cầu.'
        elif booking.status == 'FAILED':
            title = 'Đơn chưa thể thực hiện'
            message = f'Đơn {booking.booking_code} chưa tìm được nhân viên nhận việc.'
        else:
            title = 'Cập nhật lịch dịch vụ'
            message = f'Đơn {booking.booking_code} đang được CleanWise xử lý.'
        key = (booking.customer_id, booking.pk, Notification.Type.BOOKING, 'booking')
        if key not in existing_keys:
            notifications.append(Notification(
                user_id=booking.customer_id,
                title=title,
                message=message,
                type=Notification.Type.BOOKING,
                related_booking=booking,
                target='booking',
            ))
            existing_keys.add(key)

        payment = payments_by_booking.get(booking.pk)
        if payment and payment.status in (Payment.Status.SUCCESS, Payment.Status.FAILED):
            key = (booking.customer_id, booking.pk, Notification.Type.PAYMENT, 'payment')
            if key not in existing_keys:
                notifications.append(Notification(
                    user_id=booking.customer_id,
                    title='Thanh toán thành công' if payment.status == Payment.Status.SUCCESS else 'Thanh toán chưa thành công',
                    message=(
                        f'Đã ghi nhận thanh toán demo {payment.amount:,.0f}đ cho đơn {booking.booking_code}.'
                        if payment.status == Payment.Status.SUCCESS
                        else f'Giao dịch cho đơn {booking.booking_code} chưa thành công.'
                    ),
                    type=Notification.Type.PAYMENT,
                    related_booking=booking,
                    target='payment',
                ))
                existing_keys.add(key)

        assignments = assignments_by_booking.get(booking.pk, [])
        if assignments:
            assignment = assignments[0]
            key = (booking.customer_id, booking.pk, Notification.Type.ASSIGNMENT, 'booking')
            if key not in existing_keys:
                notifications.append(Notification(
                    user_id=booking.customer_id,
                    title='Đã có nhân viên nhận lịch',
                    message=f'{assignment.worker.get_full_name()} đã nhận lịch của đơn {booking.booking_code}.',
                    type=Notification.Type.ASSIGNMENT,
                    related_booking=booking,
                    related_schedule=assignment.schedule,
                    related_worker_id=getattr(
                        getattr(assignment.worker, 'worker_profile', None),
                        'pk',
                        None,
                    ),
                    target='booking',
                ))
                existing_keys.add(key)
            for worker_assignment in assignments:
                worker_key = (
                    worker_assignment.worker_id,
                    booking.pk,
                    Notification.Type.ASSIGNMENT,
                    'booking',
                )
                if worker_key in existing_keys:
                    continue
                completed = worker_assignment.schedule.status == 'COMPLETED'
                notifications.append(Notification(
                    user_id=worker_assignment.worker_id,
                    title='Lịch làm đã hoàn thành' if completed else 'Bạn đã nhận lịch mới',
                    message=(
                        f'Bạn đã hoàn thành lịch dịch vụ của đơn {booking.booking_code}.'
                        if completed
                        else f'Bạn đã nhận lịch dịch vụ của đơn {booking.booking_code}.'
                    ),
                    type=Notification.Type.ASSIGNMENT,
                    related_booking=booking,
                    related_schedule=worker_assignment.schedule,
                    related_customer=booking.customer,
                    target='booking',
                ))
                existing_keys.add(worker_key)

    complaint_ids = list(
        Complaint.objects.filter(booking_id__in=booking_ids)
        .values_list('id', flat=True)
    )
    existing_complaint_notifications = set(
        Notification.objects.filter(related_complaint_id__in=complaint_ids)
        .values_list('user_id', 'related_complaint_id', 'type')
    )
    for complaint in Complaint.objects.filter(pk__in=complaint_ids).select_related('reporter', 'booking'):
        key = (complaint.reporter_id, complaint.pk, Notification.Type.COMPLAINT)
        if key not in existing_complaint_notifications:
            notifications.append(Notification(
                user=complaint.reporter,
                title='Đã tiếp nhận phản ánh',
                message=f'CleanWise đã tiếp nhận phản ánh {complaint.code} của đơn {complaint.booking.booking_code}.',
                type=Notification.Type.COMPLAINT,
                related_booking=complaint.booking,
                related_schedule=complaint.schedule,
                related_complaint=complaint,
                target='complaint',
            ))
            existing_complaint_notifications.add(key)

    notified_user_ids = existing_notification_user_ids | {
        notification.user_id for notification in notifications
    }
    for user in demo_users:
        if user.pk not in notified_user_ids:
            notifications.append(Notification(
                user=user,
                title='Chào mừng đến với CleanWise',
                message='Tài khoản demo đã sẵn sàng sử dụng CleanWise.',
                type=Notification.Type.SYSTEM,
            ))
            notified_user_ids.add(user.pk)

    if notifications:
        Notification.objects.bulk_create(notifications, batch_size=500)
    command.stdout.write(f'Notification mới: {len(notifications)} (không gửi push).')


def seed_chat(command, demo):
    from apps.chat.models import ChatConversation, ChatConversationAssignment, ChatMessage
    from apps.worker.models import BookingAssignment

    assignments = list(
        BookingAssignment.objects.filter(
            schedule__booking_id__in=demo_booking_ids(),
            status=BookingAssignment.Status.ACCEPTED,
            schedule__status__in=('PENDING', 'IN_PROGRESS', 'COMPLETED'),
            schedule__booking__status__in=('ASSIGNED', 'IN_PROGRESS', 'COMPLETED'),
        ).select_related('worker', 'schedule__booking')
    )
    conversations = {}
    new_links = 0
    for assignment in assignments:
        pair = (assignment.schedule.booking.customer_id, assignment.worker_id)
        conversation, _ = ChatConversation.objects.get_or_create(
            customer_id=pair[0],
            worker_id=pair[1],
            defaults={'status': ChatConversation.Status.ACTIVE},
        )
        conversations[pair] = conversation
        _, created = ChatConversationAssignment.objects.get_or_create(
            assignment=assignment,
            defaults={'conversation': conversation},
        )
        new_links += int(created)

    customers_with_conversations = {customer_id for customer_id, _ in conversations}
    workers_with_conversations = {worker_id for _, worker_id in conversations}
    for index, worker in enumerate(demo['workers']):
        if worker.pk in workers_with_conversations:
            continue
        customer = demo['customers'][index % len(demo['customers'])]
        pair = (customer.pk, worker.pk)
        conversation, _ = ChatConversation.objects.get_or_create(
            customer=customer,
            worker=worker,
            defaults={'status': ChatConversation.Status.ACTIVE},
        )
        conversations[pair] = conversation
        customers_with_conversations.add(customer.pk)
        workers_with_conversations.add(worker.pk)

    for index, customer in enumerate(demo['customers']):
        if customer.pk in customers_with_conversations:
            continue
        worker = demo['workers'][index % len(demo['workers'])]
        pair = (customer.pk, worker.pk)
        conversation, _ = ChatConversation.objects.get_or_create(
            customer=customer,
            worker=worker,
            defaults={'status': ChatConversation.Status.ACTIVE},
        )
        conversations[pair] = conversation

    existing_message_keys = set(
        ChatMessage.objects.filter(client_message_id__startswith='demo-chat-')
        .values_list('client_message_id', flat=True)
    )
    messages = []
    for (customer_id, worker_id), conversation in conversations.items():
        for sequence, sender_id, text in (
            (1, customer_id, 'Chào bạn, vui lòng xác nhận giúp tôi thời gian đến làm nhé.'),
            (2, worker_id, 'Chào anh/chị, tôi đã nhận lịch và sẽ đến đúng giờ hẹn.'),
        ):
            client_id = f'demo-chat-{conversation.pk}-{sequence}'
            if client_id not in existing_message_keys:
                messages.append(ChatMessage(
                    conversation=conversation,
                    sender_id=sender_id,
                    message=text,
                    message_type=ChatMessage.MessageType.TEXT,
                    client_message_id=client_id,
                ))
                existing_message_keys.add(client_id)
    if messages:
        ChatMessage.objects.bulk_create(messages, batch_size=500)
    command.stdout.write(
        f'Chat: {len(conversations)} cuộc trò chuyện, {new_links} liên kết lịch mới, '
        f'{len(messages)} tin nhắn mới.'
    )


def validate_seed_data(command):
    from django.contrib.auth import get_user_model
    from django.db.models import Count

    from apps.authentication.models import WorkerProfile
    from apps.bookings.models import Booking, BookingActivity, BookingSchedule
    from apps.chat.models import ChatConversation, ChatMessage
    from apps.complaints.models import Complaint
    from apps.notifications.models import Notification
    from apps.payments.models import Payment
    from apps.reviews.models import Review
    from apps.wallets.models import Wallet, WalletTransaction, WorkerEarning
    from apps.worker.models import BookingAssignment, WorkerWorkingArea

    User = get_user_model()
    base_seed_keys = {
        base_booking_seed_key(index)
        for index in range(1, DEMO_BOOKING_COUNT + 1)
    }
    new_worker_seed_keys = {
        new_worker_seed_key(worker_index, booking_index)
        for worker_index in range(1, len(NEW_WORKERS) + 1)
        for booking_index in range(1, NEW_WORKER_BOOKINGS_PER_ACCOUNT + 1)
    }
    expected_seed_keys = base_seed_keys | new_worker_seed_keys
    seed_activities = list(
        BookingActivity.objects.filter(
            metadata__seed_key__in=expected_seed_keys,
            event_type=BookingActivity.EventType.BOOKING_CREATED,
        )
        .select_related('booking')
    )
    seed_activities_by_key = {}
    duplicate_seed_keys = set()
    for activity in seed_activities:
        seed_key = activity.metadata.get('seed_key')
        if seed_key in seed_activities_by_key:
            duplicate_seed_keys.add(seed_key)
        else:
            seed_activities_by_key[seed_key] = activity
    new_worker_booking_ids = {
        activity.booking_id for key, activity in seed_activities_by_key.items()
        if key in new_worker_seed_keys
    }
    base_booking_ids = {
        activity.booking_id for key, activity in seed_activities_by_key.items()
        if key in base_seed_keys
    }
    booking_ids = demo_booking_ids()
    booking_qs = Booking.objects.filter(pk__in=booking_ids)
    original_booking_count = len(base_booking_ids)
    new_worker_booking_count = len(new_worker_booking_ids)
    booking_ids = list(booking_qs.values_list('id', flat=True))
    schedules = list(
        BookingSchedule.objects.filter(booking_id__in=booking_ids)
        .select_related('booking', 'booking__service', 'booking__address')
        .order_by('scheduled_start')
    )
    assignments = list(
        BookingAssignment.objects.filter(schedule__booking_id__in=booking_ids)
        .select_related('worker', 'schedule', 'schedule__booking')
    )
    payments = list(Payment.objects.filter(booking_id__in=booking_ids).select_related('booking'))
    earnings = list(WorkerEarning.objects.filter(booking_id__in=booking_ids).select_related('schedule', 'worker'))
    reviews = list(Review.objects.filter(assignment__schedule__booking_id__in=booking_ids).select_related(
        'assignment__schedule__booking',
    ))
    complaints = list(Complaint.objects.filter(booking_id__in=booking_ids).select_related(
        'booking', 'schedule', 'reporter', 'worker',
    ))
    schedules_by_booking_id = {}
    for schedule in schedules:
        schedules_by_booking_id.setdefault(schedule.booking_id, []).append(schedule)
    accepted_counts = {}
    for assignment in assignments:
        if assignment.status == BookingAssignment.Status.ACCEPTED:
            accepted_counts[assignment.schedule.booking_id] = (
                accepted_counts.get(assignment.schedule.booking_id, 0) + 1
            )
    payments_by_booking = {}
    for payment in payments:
        payments_by_booking.setdefault(payment.booking_id, []).append(payment)
    worker_area_codes = {}
    for worker_id, ward_code in WorkerWorkingArea.objects.filter(
        worker__username__in=[phone for phone, _, _ in WORKERS + NEW_WORKERS],
    ).values_list('worker_id', 'area__ward_code'):
        worker_area_codes.setdefault(worker_id, set()).add(ward_code)

    problems = []
    expected_new_bookings = len(NEW_WORKERS) * NEW_WORKER_BOOKINGS_PER_ACCOUNT
    expected_total = DEMO_BOOKING_COUNT + expected_new_bookings
    if set(seed_activities_by_key) != expected_seed_keys:
        problems.append(
            f'expected {len(expected_seed_keys)} seed_key activities, '
            f'found {len(seed_activities_by_key)}'
        )
    if duplicate_seed_keys:
        problems.append(f'duplicate seed_key activities: {sorted(duplicate_seed_keys)}')
    if original_booking_count != DEMO_BOOKING_COUNT:
        problems.append(
            f'expected {DEMO_BOOKING_COUNT} base bookings, found {original_booking_count}'
        )
    if new_worker_booking_count != expected_new_bookings:
        problems.append(
            f'expected {expected_new_bookings} new worker bookings, '
            f'found {new_worker_booking_count}'
        )
    if len(booking_ids) != expected_total:
        problems.append(f'expected {expected_total} demo bookings, found {len(booking_ids)}')
    if Booking.objects.filter(
        pk__in=booking_ids,
        booking_code__startswith=DEMO_BOOKING_PREFIX,
    ).exists():
        problems.append('a demo booking still has the legacy DEMO-CW code')
    for activity in seed_activities_by_key.values():
        code_parts = activity.booking.booking_code.split('-')
        if (
            len(code_parts) != 3
            or code_parts[0] != 'CW'
            or len(code_parts[1]) != 6
            or not code_parts[1].isdigit()
            or len(code_parts[2]) != 5
            or not code_parts[2].isalnum()
        ):
            problems.append(
                f'{activity.booking.booking_code}: seed booking code does not match CW-YYMMDD-XXXXX'
            )
    if Payment.objects.filter(booking_id__in=booking_ids).values('booking_id').annotate(
        total=Count('id'),
    ).filter(total__gt=1).exists():
        problems.append('a demo booking has multiple payment records')

    for booking in booking_qs.select_related('customer', 'address', 'delivery_address'):
        if booking.address.customer_id != booking.customer_id:
            problems.append(f'{booking.booking_code}: address belongs to a different customer')
        if booking.delivery_address_id and booking.delivery_address.customer_id != booking.customer_id:
            problems.append(f'{booking.booking_code}: delivery address belongs to a different customer')
        if booking.status == Booking.Status.COMPLETED and booking.payment_status != Booking.PaymentStatus.PAID:
            problems.append(f'{booking.booking_code}: completed booking is not paid')
        if booking.status in (Booking.Status.ASSIGNED, Booking.Status.IN_PROGRESS) and booking.payment_status != Booking.PaymentStatus.PAID:
            problems.append(f'{booking.booking_code}: active assigned booking is not paid')
        booking_schedules = schedules_by_booking_id.get(booking.pk, [])
        accepted_count = accepted_counts.get(booking.pk, 0)
        if not booking_schedules:
            problems.append(f'{booking.booking_code}: booking has no schedule')
        elif booking.status == Booking.Status.COMPLETED and any(
            schedule.status != BookingSchedule.Status.COMPLETED for schedule in booking_schedules
        ):
            problems.append(f'{booking.booking_code}: completed booking has an unfinished schedule')
        elif booking.status == Booking.Status.ASSIGNED and (
            any(schedule.status != BookingSchedule.Status.PENDING for schedule in booking_schedules)
            or accepted_count != len(booking_schedules)
        ):
            problems.append(f'{booking.booking_code}: assigned booking schedule state is inconsistent')
        elif booking.status == Booking.Status.PENDING and accepted_count:
            problems.append(f'{booking.booking_code}: pending booking has an accepted assignment')
        elif booking.status == Booking.Status.CANCELLED and any(
            schedule.status != BookingSchedule.Status.CANCELLED for schedule in booking_schedules
        ):
            problems.append(f'{booking.booking_code}: cancelled booking has a non-cancelled schedule')
        elif booking.status == Booking.Status.FAILED and any(
            schedule.status != BookingSchedule.Status.MISSED for schedule in booking_schedules
        ):
            problems.append(f'{booking.booking_code}: failed booking has a schedule not marked missed')
        if booking.status in (Booking.Status.CANCELLED, Booking.Status.FAILED) and accepted_count:
            problems.append(f'{booking.booking_code}: closed booking still has an accepted worker')
        booking_payments = payments_by_booking.get(booking.pk, [])
        if len(booking_payments) != 1:
            problems.append(f'{booking.booking_code}: booking has no payment record')
        elif booking_payments[0].status == Payment.Status.SUCCESS:
            if booking.payment_status != Booking.PaymentStatus.PAID:
                problems.append(f'{booking.booking_code}: successful payment is not reflected on booking')
        elif booking.payment_status == Booking.PaymentStatus.PAID:
            problems.append(f'{booking.booking_code}: paid booking has no successful payment')

    schedule_by_id = {schedule.pk: schedule for schedule in schedules}
    assignment_by_schedule = {}
    busy = {}
    for assignment in assignments:
        schedule = schedule_by_id.get(assignment.schedule_id)
        if schedule is None:
            problems.append(f'assignment {assignment.pk} has no demo schedule')
            continue
        if assignment.status == BookingAssignment.Status.ACCEPTED:
            assignment_by_schedule.setdefault(schedule.pk, []).append(assignment)
            if assignment.worker.role != User.Role.WORKER:
                problems.append(f'assignment {assignment.pk} is not assigned to a worker')
            profile = WorkerProfile.objects.filter(user=assignment.worker).select_related(
                'registered_service',
            ).first()
            if (
                profile is None or profile.registered_service_id is None
                or profile.registered_service.section_code != schedule.booking.service.section_code
            ):
                problems.append(f'assignment {assignment.pk} uses a worker with the wrong service')
            elif schedule.booking.address.ward_code not in worker_area_codes.get(
                assignment.worker_id,
                set(),
            ):
                problems.append(f'assignment {assignment.pk} uses a worker outside the booking area')
            if schedule.status not in (
                BookingSchedule.Status.PENDING,
                BookingSchedule.Status.IN_PROGRESS,
                BookingSchedule.Status.COMPLETED,
            ):
                problems.append(f'assignment {assignment.pk} is attached to a non-working schedule')
            busy.setdefault(assignment.worker_id, []).append(
                (schedule.scheduled_start, schedule.scheduled_end, assignment.pk)
            )
    for worker_id, intervals in busy.items():
        intervals.sort(key=lambda item: item[0])
        for previous, current in zip(intervals, intervals[1:]):
            if current[0] < previous[1]:
                problems.append(
                    f'worker {worker_id} has overlapping demo assignments '
                    f'{previous[2]} and {current[2]}'
                )

    for payment in payments:
        if payment.customer_id != payment.booking.customer_id:
            problems.append(f'payment {payment.pk} customer does not match booking')
        if payment.amount != payment.booking.total_amount:
            problems.append(f'payment {payment.pk} amount does not match booking total')
        if payment.status == Payment.Status.SUCCESS and payment.booking.payment_status != Booking.PaymentStatus.PAID:
            problems.append(f'payment {payment.pk} is successful but booking is not paid')

    for schedule in schedules:
        if schedule.scheduled_start >= schedule.scheduled_end:
            problems.append(f'schedule {schedule.pk} has invalid time range')
        count = len(assignment_by_schedule.get(schedule.pk, []))
        if count > 1:
            problems.append(f'schedule {schedule.pk} has multiple accepted assignments')
        if schedule.status == BookingSchedule.Status.COMPLETED:
            if schedule.actual_start is None or schedule.actual_end is None:
                problems.append(f'schedule {schedule.pk} is completed without actual times')
            if count != 1:
                problems.append(f'completed schedule {schedule.pk} does not have one accepted worker')

    earnings_by_schedule = {earning.schedule_id: earning for earning in earnings}
    tx_by_key = {
        tx.idempotency_key: tx
        for tx in WalletTransaction.objects.filter(booking_id__in=booking_ids)
    }
    for schedule in schedules:
        if schedule.status == BookingSchedule.Status.COMPLETED and schedule.pk in assignment_by_schedule:
            earning = earnings_by_schedule.get(schedule.pk)
            if earning is None:
                problems.append(f'completed schedule {schedule.pk} has no WorkerEarning')
                continue
            if earning.worker_id != assignment_by_schedule[schedule.pk][0].worker_id:
                problems.append(f'earning for schedule {schedule.pk} belongs to a different worker')
            if earning.gross_amount != earning.worker_amount + earning.commission_amount:
                problems.append(f'earning for schedule {schedule.pk} does not balance')
            key = f'demo-earning:{schedule.booking.booking_code}:{schedule.sequence_no}'
            if earning.payment_method == WorkerEarning.PaymentMethod.ONLINE:
                tx = tx_by_key.get(key)
                if tx is None:
                    problems.append(f'earning for schedule {schedule.pk} has no wallet credit')
                elif (
                    tx.wallet.user_id != earning.worker_id
                    or tx.amount != earning.worker_amount
                    or tx.direction != WalletTransaction.Direction.CREDIT
                    or tx.status != WalletTransaction.Status.SUCCESS
                ):
                    problems.append(f'wallet credit for schedule {schedule.pk} does not match earning')
                if earning.wallet_credited_at is None:
                    problems.append(f'earning for schedule {schedule.pk} is not marked credited')

    for review in reviews:
        schedule = review.assignment.schedule
        if schedule.status != BookingSchedule.Status.COMPLETED or review.assignment.status != BookingAssignment.Status.ACCEPTED:
            problems.append(f'review {review.pk} is not eligible')
    for complaint in complaints:
        if complaint.reporter_role != Complaint.ReporterRole.CUSTOMER:
            problems.append(f'complaint {complaint.pk} has an invalid reporter role')
        if complaint.reporter_id != complaint.booking.customer_id:
            problems.append(f'complaint {complaint.pk} reporter does not own its booking')
        if complaint.schedule_id and complaint.schedule.booking_id != complaint.booking_id:
            problems.append(f'complaint {complaint.pk} schedule does not match its booking')
        if complaint.stage != Complaint.Stage.AFTER_SERVICE or complaint.booking.status != Booking.Status.COMPLETED:
            problems.append(f'complaint {complaint.pk} is not attached to a completed booking')

    completed_base_count = Booking.objects.filter(
        pk__in=base_booking_ids,
        status=Booking.Status.COMPLETED,
    ).count()
    if completed_base_count < int(DEMO_BOOKING_COUNT * 0.65):
        problems.append(
            f'expected at least 65% completed base bookings, found {completed_base_count}'
        )
    booking_months = {
        booking.created_at.year * 100 + booking.created_at.month
        for booking in booking_qs.only('created_at')
    }
    if len(booking_months) < 8:
        problems.append(
            f'demo booking created_at spans only {len(booking_months)} months'
        )

    demo_usernames = [phone for phone, _, _ in CUSTOMERS + WORKERS + NEW_WORKERS]
    demo_users = list(User.objects.filter(username__in=demo_usernames))
    expected_names = {
        phone: split_demo_name(full_name)
        for phone, full_name, _ in CUSTOMERS + WORKERS + NEW_WORKERS
    }
    for user in demo_users:
        if not Notification.objects.filter(user=user).exists():
            problems.append(f'{user.username} has no notification')
        conversation_filter = (
            {'customer': user}
            if user.role == User.Role.CUSTOMER else {'worker': user}
        )
        conversations = ChatConversation.objects.filter(**conversation_filter)
        if not conversations.exists():
            problems.append(f'{user.username} has no chat conversation')
        elif not ChatMessage.objects.filter(conversation__in=conversations).exists():
            problems.append(f'{user.username} has no chat messages')
        expected_email = DEMO_EMAILS.get(user.username)
        if expected_email and user.email != expected_email:
            problems.append(f'{user.username} has an unexpected demo email')
        expected_first, expected_last = expected_names[user.username]
        if (user.first_name, user.last_name) != (expected_first, expected_last):
            problems.append(f'{user.username} has an unexpected Vietnamese name split')
    for username, _, _ in CUSTOMERS:
        if not WalletTransaction.objects.filter(
            wallet__user__username=username,
            idempotency_key=f'demo-customer-opening-balance:{username}',
            amount=Decimal('100000'),
            type=WalletTransaction.Type.TOPUP,
            direction=WalletTransaction.Direction.CREDIT,
            status=WalletTransaction.Status.SUCCESS,
        ).exists():
            problems.append(f'{username} has no idempotent 100,000đ opening wallet credit')

    if problems:
        details = '; '.join(problems[:20])
        suffix = f' (và {len(problems) - 20} lỗi khác)' if len(problems) > 20 else ''
        raise CommandError(f'Kiểm tra nhất quán thất bại: {details}{suffix}')

    user_names = [phone for phone, _, _ in CUSTOMERS + WORKERS + NEW_WORKERS]
    counts = {
        'Customer': User.objects.filter(username__in=[row[0] for row in CUSTOMERS], role=User.Role.CUSTOMER).count(),
        'Worker': User.objects.filter(
            username__in=[row[0] for row in WORKERS + NEW_WORKERS],
            role=User.Role.WORKER,
        ).count(),
        'Booking': len(booking_ids),
        'CompletedBooking': completed_base_count,
        'BookingMonthBuckets': len(booking_months),
        'Schedule': len(schedules),
        'Assignment': len(assignments),
        'Payment': len(payments),
        'Wallet': Wallet.objects.filter(user__username__in=user_names).count(),
        'WalletTransaction': WalletTransaction.objects.filter(
            wallet__user__username__in=user_names,
        ).count(),
        'WorkerEarning': len(earnings),
        'Review': len(reviews),
        'Complaint': len(complaints),
        'Notification': Notification.objects.filter(
            user__username__in=user_names,
        ).count(),
    }
    command.stdout.write('Tổng hợp dữ liệu demo:')
    for label, count in counts.items():
        command.stdout.write(f'  {label}: {count}')
    command.stdout.write('Kiểm tra quan hệ, trạng thái, thanh toán, thu nhập, review và khiếu nại: OK.')


class Command(BaseCommand):
    help = 'Tạo dữ liệu demo CleanWise theo cách idempotent; mặc định chạy thử và rollback.'

    def add_arguments(self, parser):
        mode = parser.add_mutually_exclusive_group()
        mode.add_argument('--commit', action='store_true', help='Ghi dữ liệu demo vào database.')
        mode.add_argument('--dry-run', action='store_true', help='Chạy toàn bộ seed rồi rollback (mặc định).')

    def handle(self, *args, **options):
        commit = options['commit']
        self.stdout.write(
            self.style.WARNING('Chế độ ghi dữ liệu.') if commit
            else self.style.WARNING('Dry-run: không commit database và không upload Cloudinary.')
        )
        media_urls = load_demo_media(commit=commit)
        with transaction.atomic():
            demo = seed_users(self)
            seed_media(self, demo, media_urls)
            seed_new_worker_availability(self, demo)
            bookings, schedules_by_booking = seed_bookings(self, demo, media_urls)
            new_bookings, new_schedules_by_booking = seed_new_worker_bookings(self, demo)
            bookings.update(new_bookings)
            schedules_by_booking.update(new_schedules_by_booking)
            seed_wallets_and_earnings(self, demo, bookings, schedules_by_booking)
            seed_reviews(self, demo, media_urls)
            seed_complaints(self, bookings, schedules_by_booking, media_urls)
            seed_notifications(self, demo, bookings)
            seed_chat(self, demo)
            validate_seed_data(self)
            if not commit:
                transaction.set_rollback(True)
        if commit:
            self.stdout.write(self.style.SUCCESS('Đã ghi dữ liệu demo.'))
        else:
            self.stdout.write(self.style.WARNING('Dry-run hoàn tất: mọi thay đổi database đã rollback.'))
