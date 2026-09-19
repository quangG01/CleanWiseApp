from django.core.management.base import BaseCommand
from django.db import transaction

from apps.worker.models import Area

# 34 tỉnh/thành VN sau sáp nhập, hiệu lực từ 01/07/2025 (Nghị quyết Quốc hội 12/6/2025).
# Mỗi tỉnh/thành là 1 Area duy nhất, name = city (Area chưa phân biệt quận/huyện/phường/xã bên trong).
PROVINCES = [
    "TP Hà Nội",
    "TP Huế",
    "Quảng Ninh",
    "Cao Bằng",
    "Lạng Sơn",
    "Lai Châu",
    "Điện Biên",
    "Sơn La",
    "Thanh Hóa",
    "Nghệ An",
    "Hà Tĩnh",
    "Tuyên Quang",
    "Lào Cai",
    "Thái Nguyên",
    "Phú Thọ",
    "Bắc Ninh",
    "Hưng Yên",
    "TP Hải Phòng",
    "Ninh Bình",
    "Quảng Trị",
    "TP Đà Nẵng",
    "Quảng Ngãi",
    "Gia Lai",
    "Khánh Hòa",
    "Lâm Đồng",
    "Đắk Lắk",
    "TP Hồ Chí Minh",
    "Đồng Nai",
    "Tây Ninh",
    "TP Cần Thơ",
    "Vĩnh Long",
    "Đồng Tháp",
    "Cà Mau",
    "An Giang",
]


class Command(BaseCommand):
    help = "Seed 34 tỉnh/thành Việt Nam (sau sáp nhập, hiệu lực 01/07/2025) vào bảng Area."

    def handle(self, *args, **options):
        created_count = 0
        with transaction.atomic():
            for province in PROVINCES:
                obj, created = Area.objects.get_or_create(
                    city=province,
                    name=province,
                    defaults={"is_active": True},
                )
                if created:
                    created_count += 1

        total = Area.objects.count()
        self.stdout.write(self.style.SUCCESS(
            f"Đã tạo mới {created_count} khu vực. Tổng số Area hiện có: {total}."
        ))