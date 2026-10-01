import json
from pathlib import Path

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.worker.models import Area

DATA = Path(__file__).resolve().parents[2] / "data" / "vn_wards.json"


class Command(BaseCommand):
    help = "Seed 34 tỉnh/thành và phường/xã vào bảng Area (chạy lại an toàn)."

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

        Area.objects.bulk_create(
            rows,
            batch_size=500,
            update_conflicts=True,
            unique_fields=["ward_code"],
            update_fields=["city", "name", "province_code", "is_active"],
        )
        self.stdout.write(self.style.SUCCESS(
            f"Đã xử lý {len(rows)} phường/xã. Tổng Area: {Area.objects.count()}."
        ))