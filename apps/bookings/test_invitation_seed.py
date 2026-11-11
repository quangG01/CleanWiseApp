from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command, CommandError
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.bookings.models import Booking
from apps.services.models import Service
from apps.worker.models import Area, BookingAssignment, CustomerFavoriteWorker


class InvitationCardSeedTests(TestCase):
    def setUp(self):
        self.service = Service.objects.create(code='HOME_CLEANING_HOURLY', section_code='HOME_CLEANING',
            name='Dọn nhà theo giờ', description='Test', is_active=True,
            form_schema={'fields': [
                {'key': 'date', 'type': 'DATE', 'label': 'Ngày', 'required': True},
                {'key': 'start_time', 'type': 'TIME', 'label': 'Giờ', 'required': True},
                {'key': 'duration', 'type': 'SINGLE_SELECT', 'label': 'Thời lượng', 'required': True,
                 'options': [{'label': '2 giờ', 'value': '2_HOURS'}, {'label': '3 giờ', 'value': '3_HOURS'}]},
                {'key': 'additional_services', 'type': 'MULTI_SELECT', 'label': 'Thêm', 'required': False, 'options': []},
            ]}, pricing_config={'currency': 'VND', 'base_prices': {'2_HOURS': 150000, '3_HOURS': 210000}})
        self.area = Area.objects.create(name='Quận 1', city='TP Hồ Chí Minh', ward_code='TESTCARD')

    def seed(self):
        call_command('seed_invitation_card_tests', area_id=self.area.id, batch='UNITTEST', stdout=StringIO())

    @override_settings(DEBUG=True, SETTINGS_MODULE='core.settings.dev')
    def test_seed_creates_future_claimable_orders_and_preserves_on_repeat(self):
        from apps.worker.assignment_service import list_available_workers_for_schedule
        self.seed()
        User = get_user_model()
        customer = User.objects.get(username='card_test_customer')
        self.assertTrue(customer.check_password('Cards@Test123'))
        self.assertEqual(customer.role, 'CUSTOMER')
        bookings = Booking.objects.filter(customer=customer)
        self.assertEqual(bookings.count(), 5)
        for booking in bookings:
            schedule = booking.schedules.get()
            self.assertGreater(schedule.scheduled_start, timezone.now())
            self.assertEqual(booking.payments.get().method, 'CASH')
            self.assertEqual(len(list_available_workers_for_schedule(schedule_id=schedule.id)), 2)
        self.assertEqual(CustomerFavoriteWorker.objects.filter(customer=customer).count(), 2)
        self.assertFalse(BookingAssignment.objects.exists())
        customer.set_password('ChangedOnlyForTest123')
        customer.save(update_fields=['password'])
        self.seed()
        customer.refresh_from_db()
        self.assertTrue(customer.check_password('ChangedOnlyForTest123'))
        self.assertEqual(Booking.objects.filter(customer=customer).count(), 5)
        self.assertEqual(User.objects.filter(username__startswith='card_test_').count(), 3)

    @override_settings(DEBUG=False, SETTINGS_MODULE='core.settings.prod')
    def test_production_guard_does_not_create_data(self):
        with self.assertRaises(CommandError):
            self.seed()
        self.assertFalse(get_user_model().objects.filter(username__startswith='card_test_').exists())

    @override_settings(DEBUG=True, SETTINGS_MODULE='core.settings.dev')
    def test_tab_seed_creates_expected_reasons_and_preserves_repeat_state(self):
        from apps.worker.assignment_service import list_available_workers_for_schedule
        from apps.wallets.models import Wallet
        from apps.notifications.models import Notification
        call_command('seed_worker_tab_tests', area_id=self.area.id, batch='UNITTEST', stdout=StringIO())
        customer = get_user_model().objects.get(username='tabs_test_customer')
        self.assertTrue(customer.check_password('Tabs@Test123'))
        self.assertEqual(Booking.objects.filter(customer=customer).count(), 7)
        reasons = [[], ['Trùng lịch'], ['Không đủ số dư'], ['Ngoài khu vực'],
                   ['Không phù hợp dịch vụ'], ['Hồ sơ chưa được duyệt']]
        for index, expected in enumerate(reasons, start=1):
            schedule = Booking.objects.get(booking_code=f'CW-TABS-UNITTEST-{index:02d}').schedules.get()
            self.assertLess(schedule.preferred_worker_expires_at, timezone.now())
            requested = list_available_workers_for_schedule(schedule_id=schedule.id, group='requested')
            self.assertEqual(len(requested), 1)
            self.assertEqual(requested[0].unavailable_reasons, expected)
            self.assertEqual(len(list_available_workers_for_schedule(schedule_id=schedule.id, group='favorites')), 6)
            suitable = list_available_workers_for_schedule(schedule_id=schedule.id)
            self.assertTrue(all(worker.can_receive_invitation for worker in suitable))
            self.assertIn('tabs_test_worker_07', [worker.username for worker in suitable])
        self.assertEqual(BookingAssignment.objects.count(), 1)
        self.assertFalse(Notification.objects.exists())
        customer.set_password('PreserveTestPassword123')
        customer.save(update_fields=['password'])
        Wallet.objects.filter(user__username='tabs_test_worker_01').update(balance=123456)
        call_command('seed_worker_tab_tests', area_id=self.area.id, batch='UNITTEST', stdout=StringIO())
        customer.refresh_from_db()
        self.assertTrue(customer.check_password('PreserveTestPassword123'))
        self.assertEqual(Wallet.objects.get(user__username='tabs_test_worker_01').balance, 123456)
        self.assertEqual(Booking.objects.filter(customer=customer).count(), 7)
        self.assertEqual(BookingAssignment.objects.count(), 1)

    @override_settings(DEBUG=False, SETTINGS_MODULE='core.settings.prod')
    def test_tab_seed_refuses_production_settings(self):
        with self.assertRaises(CommandError):
            call_command('seed_worker_tab_tests', area_id=self.area.id, stdout=StringIO())
        self.assertFalse(get_user_model().objects.filter(username__startswith='tabs_test_').exists())
