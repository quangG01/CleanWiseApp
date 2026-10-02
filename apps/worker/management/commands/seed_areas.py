import json
from pathlib import Path

from django.core.management.base import BaseCommand
from django.core.cache import cache
from django.db import transaction

from apps.common.cache_utils import bump_version
from apps.worker.models import Area, WorkerWorkingArea

DATA = Path(__file__).resolve().parents[2] / "data" / "vn_wards.json"


class Command(BaseCommand):
    help = "Seed 34 tỉnh/thành và phường/xã vào bảng Area (chạy lại an toàn)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--reset", action="store_true",
            help="Xóa toàn bộ Area và khu vực làm việc đã chọn của nhân viên trước khi seed.",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        provinces = json.loads(DATA.read_text(encoding="utf-8"))
        rows = []
        for p in provinces:
            for w in p["Wards"]:
                rows.append(
                    Area(
                        city=p["FullName"],
                        name=w["FullName"],
                        province_code=str(p["Code"]),
                        ward_code=str(w["Code"]),
                        is_active=True,
                    )
                )

        if options["reset"]:
            links, _ = WorkerWorkingArea.objects.all().delete()
            areas, _ = Area.objects.all().delete()
            self.stdout.write(f"Đã xóa {areas} Area và {links} liên kết khu vực làm việc.")

        Area.objects.bulk_create(
            rows,
            batch_size=500,
            update_conflicts=True,
            unique_fields=["ward_code"],
            update_fields=["city", "name", "province_code", "is_active"],
        )
        # bulk_create does not send post_save signals.
        def invalidate_cache():
            bump_version("areas")
            cache.delete("areas:provinces")

        transaction.on_commit(invalidate_cache)
        self.stdout.write(self.style.SUCCESS(
            f"Đã xử lý {len(rows)} phường/xã. Tổng Area: {Area.objects.count()}."
        ))
