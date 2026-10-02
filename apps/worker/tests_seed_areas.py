import json
from io import StringIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.management import call_command
from django.db import IntegrityError
from django.test import TestCase

from apps.common.cache_utils import versioned_key
from apps.worker.management.commands.seed_areas import DATA
from apps.worker.models import Area, WorkerWorkingArea


class SeedAreasTests(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.old_area = Area.objects.create(
            city="Tỉnh cũ", name="Xã cũ", province_code="OLD", ward_code="OLD",
        )
        self.worker = get_user_model().objects.create_user(
            username="seed-worker", email="seed-worker@example.com", role="WORKER",
        )
        self.link = WorkerWorkingArea.objects.create(worker=self.worker, area=self.old_area)
        self.provinces = json.loads(DATA.read_text(encoding="utf-8"))
        self.count = sum(len(province["Wards"]) for province in self.provinces)

    def seed(self, **options):
        with self.captureOnCommitCallbacks(execute=True):
            call_command("seed_areas", stdout=StringIO(), **options)

    def test_reset_replaces_old_areas_and_removes_worker_links(self):
        self.assertEqual(len(self.provinces), 34)
        self.seed(reset=True)
        self.assertEqual(Area.objects.count(), self.count)
        self.assertFalse(Area.objects.filter(ward_code="OLD").exists())
        self.assertFalse(WorkerWorkingArea.objects.exists())
        self.assertTrue(get_user_model().objects.filter(pk=self.worker.pk).exists())

    def test_default_seed_is_idempotent_and_preserves_links_and_ids(self):
        self.seed()
        ward = Area.objects.exclude(ward_code="OLD").first()
        ward_id = ward.pk
        ward.name = "Tên lỗi thời"
        ward.is_active = False
        ward.save()
        self.seed()
        ward.refresh_from_db()
        self.assertEqual(ward.pk, ward_id)
        self.assertNotEqual(ward.name, "Tên lỗi thời")
        self.assertTrue(ward.is_active)
        self.assertEqual(Area.objects.count(), self.count + 1)
        self.assertTrue(WorkerWorkingArea.objects.filter(pk=self.link.pk).exists())

    def test_failed_insert_rolls_back_deletions_and_leaves_cache_intact(self):
        key = versioned_key("areas", "list", "01")
        cache.set("areas:provinces", ["old"])
        with patch.object(Area.objects, "bulk_create", side_effect=IntegrityError("seed failed")):
            with self.assertRaises(IntegrityError):
                self.seed(reset=True)
        self.assertTrue(Area.objects.filter(pk=self.old_area.pk).exists())
        self.assertTrue(WorkerWorkingArea.objects.filter(pk=self.link.pk).exists())
        self.assertEqual(cache.get("areas:provinces"), ["old"])
        self.assertEqual(versioned_key("areas", "list", "01"), key)

    def test_seed_invalidates_both_area_and_province_caches_after_commit(self):
        key = versioned_key("areas", "list", "01")
        cache.set("areas:provinces", ["old"])
        self.seed()
        self.assertIsNone(cache.get("areas:provinces"))
        self.assertNotEqual(versioned_key("areas", "list", "01"), key)
