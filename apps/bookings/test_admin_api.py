from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from apps.addresses.models import CustomerAddress
from apps.authentication.models import WorkerProfile
from apps.payments.models import Payment
from apps.services.models import Service
from apps.wallets.models import Wallet
from apps.worker.models import Area, BookingAssignment, WorkerWorkingArea

from .booking_service import create_booking
from .models import Booking, BookingActivity, BookingSchedule

User = get_user_model()


class AdminBookingApiTests(APITestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username='booking-admin', email='booking-admin@example.com',
            password='test', role=User.Role.ADMIN,
        )
        self.customer = User.objects.create_user(
            username='booking-customer-admin-test',
            email='booking-customer-admin-test@example.com',
            password='test', role=User.Role.CUSTOMER,
            first_name='An', last_name='Nguyen', phone_number='0911111111',
        )
        self.worker = User.objects.create_user(
            username='booking-worker-admin-test',
            email='booking-worker-admin-test@example.com',
            password='test', role=User.Role.WORKER,
            first_name='Binh', last_name='Tran', phone_number='0922222222',
        )
        self.address = CustomerAddress.objects.create(
            customer=self.customer,
            receiver_name='Nguyễn Văn An', receiver_phone='0911111111',
            address_line='01 Nguyễn Huệ', ward='Bến Nghé', city='TP.HCM',
        )
        self.service = Service.objects.create(
            code='ADMIN_BOOKING_SERVICE', section_code='HOME_CLEANING',
            name='Dọn nhà admin test', description='Test',
            form_schema={
                'fields': [
                    {'key': 'date', 'type': 'DATE', 'label': 'Ngày', 'required': True},
                    {'key': 'start_time', 'type': 'TIME', 'label': 'Giờ', 'required': True},
                    {
                        'key': 'duration', 'type': 'SINGLE_SELECT',
                        'label': 'Thời lượng', 'required': True,
                        'options': [{'label': '2 giờ', 'value': '2_HOURS'}],
                    },
                ],
            },
            pricing_config={'currency': 'VND', 'base_prices': {'2_HOURS': 150000}},
            is_active=True,
        )
        WorkerProfile.objects.create(
            user=self.worker, status=WorkerProfile.Status.ACTIVE,
            registered_service=self.service, average_rating=Decimal('4.80'),
        )
        area = Area.objects.create(name='Quận 1', city='TP.HCM')
        WorkerWorkingArea.objects.create(worker=self.worker, area=area)
        Wallet.objects.create(user=self.worker, balance=Decimal('500000'))
        self.booking = self._create_booking()
        self.schedule = self.booking.schedules.get()
        self.client.force_authenticate(self.admin)

    def _service_data(self, days=2):
        start = self._future_start(days)
        return {
            'date': start.strftime('%Y-%m-%d'),
            'start_time': start.strftime('%H:%M'),
            'duration': '2_HOURS',
        }

    @staticmethod
    def _future_start(days):
        return (timezone.localtime() + timedelta(days=days)).replace(
            hour=10, minute=0, second=0, microsecond=0,
        )

    def _create_booking(self, days=2):
        return create_booking(
            customer=self.customer,
            service_id=self.service.id,
            address_id=self.address.id,
            service_data=self._service_data(days),
            payment_method='CASH',
        )

    def test_admin_can_list_filter_and_view_booking(self):
        response = self.client.get(reverse('admin-booking-list-create'), {
            'search': self.booking.booking_code,
            'status': Booking.Status.PENDING,
            'unassigned': 'true',
        })
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(response.data['data']['count'], 1)
        self.assertEqual(response.data['data']['results'][0]['booking_code'], self.booking.booking_code)

        detail = self.client.get(reverse('admin-booking-detail', args=[self.booking.id]))
        self.assertEqual(detail.status_code, status.HTTP_200_OK, detail.data)
        self.assertEqual(detail.data['data']['schedules'][0]['id'], self.schedule.id)

    def test_non_admin_cannot_list_bookings(self):
        self.client.force_authenticate(self.customer)
        response = self.client.get(reverse('admin-booking-list-create'))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_unassigned_filter_excludes_failed_before_pagination(self):
        failed = self._create_booking(days=3)
        failed.status = Booking.Status.FAILED
        failed.save(update_fields=['status'])
        url = reverse('admin-booking-list-create')
        for value in ('true', '1'):
            response = self.client.get(url, {'unassigned': value, 'page_size': 1})
            self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
            self.assertEqual(response.data['data']['count'], 1)
            self.assertFalse(response.data['data']['has_next'])
            self.assertEqual(response.data['data']['results'][0]['id'], self.booking.id)
        # Failed orders remain accessible when not filtering unassigned work.
        response = self.client.get(url, {'status': Booking.Status.FAILED})
        self.assertEqual(response.data['data']['count'], 1)
        response = self.client.get(url, {'status': Booking.Status.FAILED, 'unassigned': 'true'})
        self.assertEqual(response.data['data']['count'], 0)

    def test_worker_search_matches_name_phone_username_and_id(self):
        url = reverse('admin-worker-search')
        for search in ('Binh Tran', 'Tran Binh', '092222', self.worker.username, str(self.worker.id)):
            response = self.client.get(url, {'search': search})
            self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
            self.assertEqual(response.data['data']['count'], 1)
            self.assertEqual(response.data['data']['results'][0]['id'], self.worker.id)
        response = self.client.get(url, {'search': 'nonexistent-worker'})
        self.assertEqual(response.data['data']['count'], 0)

    def test_unassigned_filter_excludes_overdue_and_non_pending_sessions(self):
        now = timezone.now()
        expired = self._create_booking(days=3)
        expired.schedules.update(scheduled_start=now - timedelta(hours=3), scheduled_end=now - timedelta(hours=1))
        started = self._create_booking(days=4)
        started.schedules.update(scheduled_start=now - timedelta(minutes=1), scheduled_end=now + timedelta(hours=2))
        missed = self._create_booking(days=5)
        missed.schedules.update(status=BookingSchedule.Status.MISSED)
        response = self.client.get(reverse('admin-booking-list-create'), {'unassigned': 'true', 'page_size': 1})
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['data']['count'], 1)
        self.assertEqual(response.data['data']['results'][0]['id'], self.booking.id)
        self.assertFalse(response.data['data']['has_next'])

    def test_unassigned_filter_keeps_booking_with_future_unassigned_session(self):
        now = timezone.now()
        self.schedule.scheduled_start = now - timedelta(hours=3)
        self.schedule.scheduled_end = now - timedelta(hours=1)
        self.schedule.save(update_fields=['scheduled_start', 'scheduled_end'])
        future = BookingSchedule.objects.create(
            booking=self.booking, sequence_no=2,
            scheduled_start=now + timedelta(days=1), scheduled_end=now + timedelta(days=1, hours=2),
        )
        url = reverse('admin-booking-list-create')
        self.assertEqual(self.client.get(url, {'unassigned': 'true'}).data['data']['count'], 1)
        BookingAssignment.objects.create(schedule=future, worker=self.worker, status=BookingAssignment.Status.ACCEPTED)
        self.assertEqual(self.client.get(url, {'unassigned': 'true'}).data['data']['count'], 0)

    def test_worker_search_paginated_and_restricted_to_active_workers(self):
        for index in range(21):
            worker = User.objects.create_user(
                username=f'lookup-worker-{index}', email=f'lookup-{index}@example.com',
                role=User.Role.WORKER, first_name='Lookup', last_name=str(index),
            )
            WorkerProfile.objects.create(user=worker, status=WorkerProfile.Status.ACTIVE)
        url = reverse('admin-worker-search')
        first = self.client.get(url).data['data']
        second = self.client.get(url, {'page': 2}).data['data']
        self.assertEqual(first['count'], 22)
        self.assertEqual(len(first['results']), 20)
        self.assertTrue(first['has_next'])
        self.assertEqual(len(second['results']), 2)
        self.assertFalse({w['id'] for w in first['results']} & {w['id'] for w in second['results']})
        WorkerProfile.objects.filter(user=self.worker).update(status=WorkerProfile.Status.SUSPENDED)
        self.assertEqual(self.client.get(url).data['data']['count'], 21)
        WorkerProfile.objects.filter(user=self.worker).update(status=WorkerProfile.Status.ACTIVE)
        self.worker.is_active = False
        self.worker.save(update_fields=['is_active'])
        self.assertEqual(self.client.get(url).data['data']['count'], 21)

    def test_non_admin_cannot_search_workers(self):
        self.client.force_authenticate(self.customer)
        response = self.client.get(reverse('admin-worker-search'))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_admin_can_create_booking_for_customer(self):
        response = self.client.post(reverse('admin-booking-list-create'), {
            'customer_id': self.customer.id,
            'service_id': self.service.id,
            'address_id': self.address.id,
            'service_data': self._service_data(3),
            'payment_method': 'CASH',
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        created = Booking.objects.get(pk=response.data['data']['id'])
        self.assertEqual(created.customer, self.customer)
        self.assertTrue(created.activities.filter(
            event_type=BookingActivity.EventType.BOOKING_CREATED,
            actor=self.admin,
        ).exists())

    def test_available_workers_and_invitation(self):
        available = self.client.get(reverse('admin-schedule-workers', args=[self.schedule.id]))
        self.assertEqual(available.status_code, status.HTTP_200_OK, available.data)
        self.assertEqual(available.data['data']['count'], 1)
        self.assertEqual(available.data['data']['results'][0]['id'], self.worker.id)

        assigned = self.client.post(
            reverse('admin-booking-schedule-assign', args=[self.schedule.id]),
            {'worker_id': self.worker.id, 'reason': 'Đã xác nhận'},
            format='json',
        )
        self.assertEqual(assigned.status_code, status.HTTP_201_CREATED, assigned.data)
        assignment = BookingAssignment.objects.get(schedule=self.schedule)
        self.assertEqual(assignment.status, BookingAssignment.Status.PENDING)
        self.booking.refresh_from_db()
        self.assertEqual(self.booking.status, Booking.Status.PENDING)
        self.assertIsNone(assignment.commission_reserved)
        self.assertEqual(assignment.assigned_by, self.admin)

    def test_admin_can_unassign_worker(self):
        self.client.post(
            reverse('admin-booking-schedule-assign', args=[self.schedule.id]),
            {'worker_id': self.worker.id}, format='json',
        )
        from apps.worker.assignment_service import claim_schedule
        claim_schedule(schedule_id=self.schedule.id, worker=self.worker)
        response = self.client.post(
            reverse('admin-schedule-unassign', args=[self.schedule.id]),
            {'reason': 'Đổi kế hoạch'}, format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(
            BookingAssignment.objects.get(schedule=self.schedule).status,
            BookingAssignment.Status.CANCELLED,
        )

    def test_admin_can_reschedule_pending_schedule(self):
        new_start = self._future_start(5)
        response = self.client.patch(
            reverse('admin-schedule-update', args=[self.schedule.id]),
            {
                'scheduled_start': new_start.isoformat(),
                'scheduled_end': (new_start + timedelta(hours=2)).isoformat(),
                'reason': 'Khách yêu cầu đổi lịch',
            },
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.schedule.refresh_from_db()
        self.assertAlmostEqual(self.schedule.scheduled_start, new_start, delta=timedelta(seconds=1))

    def test_admin_can_cancel_booking_and_read_timeline(self):
        response = self.client.post(
            reverse('admin-booking-cancel', args=[self.booking.id]),
            {'reason': 'Khách yêu cầu qua tổng đài'}, format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.booking.refresh_from_db()
        self.assertEqual(self.booking.status, Booking.Status.CANCELLED)

        timeline = self.client.get(reverse('admin-booking-timeline', args=[self.booking.id]))
        self.assertEqual(timeline.status_code, status.HTTP_200_OK, timeline.data)
        events = {item['event_type'] for item in timeline.data['data']['results']}
        self.assertIn(BookingActivity.EventType.BOOKING_CANCELLED, events)

    def test_bulk_assign_returns_per_schedule_result(self):
        response = self.client.post(reverse('admin-schedule-bulk-assign'), {
            'booking_id': self.booking.id,
            'schedule_ids': [self.schedule.id],
            'worker_id': self.worker.id,
            'reason': 'Phân công gói',
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertEqual(response.data['data']['assigned'][0]['schedule_id'], self.schedule.id)

    def test_admin_can_complete_in_progress_schedule(self):
        assigned = self.client.post(
            reverse('admin-booking-schedule-assign', args=[self.schedule.id]),
            {'worker_id': self.worker.id}, format='json',
        )
        self.assertEqual(assigned.status_code, status.HTTP_201_CREATED, assigned.data)
        from apps.worker.assignment_service import claim_schedule
        claim_schedule(schedule_id=self.schedule.id, worker=self.worker)
        self.schedule.status = self.schedule.Status.IN_PROGRESS
        self.schedule.actual_start = timezone.now() - timedelta(hours=1)
        self.schedule.save(update_fields=['status', 'actual_start', 'updated_at'])
        self.booking.status = Booking.Status.IN_PROGRESS
        self.booking.save(update_fields=['status', 'updated_at'])

        response = self.client.post(
            reverse('admin-schedule-complete', args=[self.schedule.id]),
            {'reason': 'Ứng dụng nhân viên gặp lỗi', 'completion_note': 'Đã gọi xác nhận'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.schedule.refresh_from_db()
        self.booking.refresh_from_db()
        self.assertEqual(self.schedule.status, self.schedule.Status.COMPLETED)
        self.assertEqual(self.booking.status, Booking.Status.COMPLETED)

    def test_customer_cancel_records_cancel_and_refund_timeline(self):
        self.booking.payment_status = Booking.PaymentStatus.PAID
        self.booking.save(update_fields=['payment_status', 'updated_at'])
        payment = self.booking.payments.get()
        payment.status = Payment.Status.SUCCESS
        payment.paid_at = timezone.now()
        payment.save(update_fields=['status', 'paid_at', 'updated_at'])

        self.client.force_authenticate(self.customer)
        response = self.client.post(
            reverse('customer-booking-cancel', args=[self.booking.id]),
            {'reason': 'Thay đổi kế hoạch'}, format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        events = set(self.booking.activities.values_list('event_type', flat=True))
        self.assertIn(BookingActivity.EventType.BOOKING_CANCELLED, events)
        self.assertIn(BookingActivity.EventType.REFUND_CREATED, events)
        self.assertIn(BookingActivity.EventType.REFUND_COMPLETED, events)
        payment.refresh_from_db()
        self.assertEqual(payment.status, Payment.Status.REFUNDED)


    def _invite(self):
        return self.client.post(reverse('admin-booking-schedule-assign', args=[self.schedule.id]),
                                {'worker_id': self.worker.id, 'note': 'Mời bạn nhận buổi này', 'response_minutes': 15}, format='json')

    def test_invitation_accepts_existing_record_and_reserves_commission(self):
        invitation = self._invite().data['data']
        self.client.force_authenticate(self.worker)
        response = self.client.post(reverse('worker-invitation-respond', args=[invitation['id']]), {'action': 'accept'}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        assignment = BookingAssignment.objects.get(pk=invitation['id'])
        self.assertEqual(assignment.status, 'ACCEPTED')
        self.assertEqual(assignment.assigned_by, self.admin)
        self.assertGreater(assignment.commission_reserved, 0)
        self.assertEqual(BookingAssignment.objects.filter(schedule=self.schedule).count(), 1)
        self.assertEqual(self.client.post(reverse('worker-invitation-respond', args=[assignment.id]), {'action': 'accept'}, format='json').status_code, 200)

    def test_invitation_blocks_duplicate_and_other_worker_claim(self):
        self.assertEqual(self._invite().status_code, 201)
        self.assertEqual(self._invite().status_code, 400)
        other = User.objects.create_user(username='other-invited-worker', email='other-invited@example.com', role='WORKER')
        WorkerProfile.objects.create(user=other, status='ACTIVE', registered_service=self.service)
        WorkerWorkingArea.objects.create(worker=other, area=self.worker.working_areas.first().area)
        Wallet.objects.create(user=other, balance=500000)
        self.client.force_authenticate(other)
        response = self.client.post(reverse('worker-schedule-claim', args=[self.schedule.id]), {}, format='json')
        self.assertEqual(response.status_code, 400, response.data)
        available = self.client.get(reverse('worker-schedule-available'), {'booking_id': self.booking.id})
        self.assertEqual(available.data['data'], [])
        invitation = BookingAssignment.objects.get(schedule=self.schedule)
        self.assertEqual(self.client.post(reverse('worker-invitation-respond', args=[invitation.id]), {'action': 'decline'}, format='json').status_code, 404)

    def test_decline_and_withdraw_keep_invitation_history(self):
        invitation = self._invite().data['data']
        self.client.force_authenticate(self.worker)
        response = self.client.post(reverse('worker-invitation-respond', args=[invitation['id']]), {'action': 'decline'}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        self.client.force_authenticate(self.admin)
        self.assertEqual(self._invite().status_code, 201)
        response = self.client.post(reverse('admin-invitation-withdraw', args=[self.schedule.id]), {'reason': 'Đổi kế hoạch'}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(set(BookingAssignment.objects.filter(schedule=self.schedule).values_list('status', flat=True)), {'REJECTED', 'CANCELLED'})

    def test_expired_invitation_cannot_accept_and_opens_again(self):
        from apps.worker.invitation_service import expire_invitations
        invitation = self._invite().data['data']
        BookingAssignment.objects.filter(pk=invitation['id']).update(expired_at=timezone.now() - timedelta(seconds=1))
        self.client.force_authenticate(self.worker)
        response = self.client.post(reverse('worker-invitation-respond', args=[invitation['id']]), {'action': 'accept'}, format='json')
        self.assertEqual(response.status_code, 400, response.data)
        expire_invitations()
        self.assertEqual(BookingAssignment.objects.get(pk=invitation['id']).status, 'EXPIRED')
        self.client.force_authenticate(self.admin)
        self.assertEqual(self._invite().status_code, 201)

    def test_accept_rechecks_wallet_and_rolls_back_invitation(self):
        invitation = self._invite().data['data']
        Wallet.objects.filter(user=self.worker).update(balance=0)
        self.client.force_authenticate(self.worker)
        response = self.client.post(reverse('worker-invitation-respond', args=[invitation['id']]), {'action': 'accept'}, format='json')
        self.assertEqual(response.status_code, 400, response.data)
        self.assertEqual(BookingAssignment.objects.get(pk=invitation['id']).status, 'PENDING')

    def test_invitation_notification_and_worker_detail(self):
        from apps.notifications.models import Notification
        invitation = self._invite().data['data']
        notification = Notification.objects.filter(user=self.worker, title='Lời mời nhận việc từ admin').get()
        self.assertEqual(notification.related_schedule, self.schedule)
        self.assertEqual(notification.navigation_source, 'available')
        detail = self.client.get(reverse('admin-booking-detail', args=[self.booking.id])).data['data']['schedules'][0]
        self.assertIsNone(detail['current_assignment'])
        self.assertEqual(detail['invitation']['id'], invitation['id'])
        self.client.force_authenticate(self.worker)
        detail = self.client.get(reverse('worker-booking-schedules', args=[self.booking.id])).data['data'][0]
        self.assertNotIn('note', detail['invitation'])
        self.assertNotIn('invitation_note', invitation)
        self.assertEqual(detail['invitation']['status'], 'PENDING')

    def test_invitation_reschedule_closes_pending_request(self):
        invitation = self._invite().data['data']
        start = self._future_start(5)
        response = self.client.patch(reverse('admin-schedule-update', args=[self.schedule.id]), {'scheduled_start': start.isoformat(), 'scheduled_end': (start + timedelta(hours=2)).isoformat(), 'reason': 'Khách đổi lịch'}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(BookingAssignment.objects.get(pk=invitation['id']).status, 'CANCELLED')

    def test_customer_priority_requires_withdrawal(self):
        self.schedule.preferred_worker = self.worker
        self.schedule.preferred_worker_expires_at = timezone.now() + timedelta(minutes=30)
        self.schedule.save()
        self.assertEqual(self._invite().status_code, 400)
        response = self.client.post(reverse('admin-invitation-withdraw', args=[self.schedule.id]), {'reason': 'Khách đồng ý đổi nhân viên'}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(self._invite().status_code, 201)


    def test_waiting_filter_keeps_unassigned_and_clears_after_accept(self):
        invitation = self._invite().data['data']
        url = reverse('admin-booking-list-create')
        data = self.client.get(url, {'invitation_state': 'waiting', 'unassigned': 'true'}).data['data']
        self.assertEqual(data['count'], 1)
        self.assertEqual(data['results'][0]['waiting_invitations'], 1)
        self.client.force_authenticate(self.worker)
        self.client.post(reverse('worker-invitation-respond', args=[invitation['id']]), {'action': 'accept'}, format='json')
        self.client.force_authenticate(self.admin)
        self.assertEqual(self.client.get(url, {'invitation_state': 'waiting'}).data['data']['count'], 0)

    def test_package_invitation_blocks_only_invited_session(self):
        from apps.worker.assignment_service import claim_booking_package
        second = BookingSchedule.objects.create(booking=self.booking, sequence_no=2,
            scheduled_start=self.schedule.scheduled_start + timedelta(days=1), scheduled_end=self.schedule.scheduled_end + timedelta(days=1))
        invitation = self._invite().data['data']
        other = User.objects.create_user(username='package-other', email='package-other@example.com', role='WORKER')
        WorkerProfile.objects.create(user=other, status='ACTIVE', registered_service=self.service)
        WorkerWorkingArea.objects.create(worker=other, area=self.worker.working_areas.first().area)
        Wallet.objects.create(user=other, balance=500000)
        result = claim_booking_package(booking_id=self.booking.id, worker=other, schedule_ids=[self.schedule.id, second.id])
        self.assertEqual([a.schedule_id for a in result['claimed']], [second.id])
        self.assertEqual(result['skipped'][0]['schedule_id'], self.schedule.id)
        self.assertEqual(BookingAssignment.objects.get(pk=invitation['id']).status, 'PENDING')

    def test_accept_rechecks_time_conflict(self):
        invitation = self._invite().data['data']
        other_booking = self._create_booking()
        other_schedule = other_booking.schedules.get()
        BookingAssignment.objects.create(schedule=other_schedule, worker=self.worker, status='ACCEPTED')
        self.client.force_authenticate(self.worker)
        response = self.client.post(reverse('worker-invitation-respond', args=[invitation['id']]), {'action': 'accept'}, format='json')
        self.assertEqual(response.status_code, 400, response.data)
        self.assertEqual(BookingAssignment.objects.get(pk=invitation['id']).status, 'PENDING')

    def test_customer_favorite_is_marked_for_admin(self):
        from apps.worker.models import CustomerFavoriteWorker
        CustomerFavoriteWorker.objects.create(customer=self.customer, worker=self.worker)
        data = self.client.get(reverse('admin-schedule-workers', args=[self.schedule.id])).data['data']
        self.assertTrue(data['results'][0]['is_customer_favorite'])

    def test_favorite_tab_keeps_conflicting_worker_but_disables_invitation(self):
        from apps.worker.models import CustomerFavoriteWorker
        CustomerFavoriteWorker.objects.create(customer=self.customer, worker=self.worker)
        conflict = self._create_booking().schedules.get()
        BookingAssignment.objects.create(schedule=conflict, worker=self.worker, status='ACCEPTED')
        url = reverse('admin-schedule-workers', args=[self.schedule.id])
        self.assertEqual(self.client.get(url).data['data']['count'], 0)
        data = self.client.get(url, {'group': 'favorites'}).data['data']
        self.assertEqual(data['count'], 1)
        worker = data['results'][0]
        self.assertFalse(worker['can_receive_invitation'])
        self.assertTrue(worker['has_time_conflict'])
        self.assertEqual(worker['unavailable_reasons'], ['Trùng lịch'])

    def test_requested_tab_is_schedule_specific_and_distinct_from_favorites(self):
        from apps.worker.models import CustomerFavoriteWorker
        CustomerFavoriteWorker.objects.create(customer=self.customer, worker=self.worker)
        url = reverse('admin-schedule-workers', args=[self.schedule.id])
        self.assertEqual(self.client.get(url, {'group': 'requested'}).data['data']['count'], 0)
        self.schedule.preferred_worker = self.worker
        self.schedule.preferred_worker_expires_at = timezone.now() - timedelta(minutes=1)
        self.schedule.save()
        data = self.client.get(url, {'group': 'requested'}).data['data']
        self.assertEqual(data['count'], 1)
        self.assertTrue(data['results'][0]['is_customer_requested'])
        self.assertTrue(data['results'][0]['can_receive_invitation'])
        second = BookingSchedule.objects.create(booking=self.booking, sequence_no=2,
            scheduled_start=self.schedule.scheduled_start + timedelta(days=1),
            scheduled_end=self.schedule.scheduled_end + timedelta(days=1))
        self.assertEqual(self.client.get(reverse('admin-schedule-workers', args=[second.id]), {'group': 'requested'}).data['data']['count'], 0)

    def test_requested_tab_explains_insufficient_balance(self):
        self.schedule.preferred_worker = self.worker
        self.schedule.save()
        Wallet.objects.filter(user=self.worker).update(balance=0)
        data = self.client.get(reverse('admin-schedule-workers', args=[self.schedule.id]), {'group': 'requested'}).data['data']
        self.assertFalse(data['results'][0]['can_receive_invitation'])
        self.assertEqual(data['results'][0]['unavailable_reasons'], ['Không đủ số dư'])

    def test_favorite_tab_keeps_worker_with_missing_profile_and_excludes_other_customers(self):
        from apps.worker.models import CustomerFavoriteWorker
        worker = User.objects.create_user(username='no-profile-favorite', email='no-profile@example.com', role='WORKER')
        CustomerFavoriteWorker.objects.create(customer=self.customer, worker=worker)
        other_customer = User.objects.create_user(username='other-favorite-customer-admin', email='other-favorite-admin@example.com', role='CUSTOMER')
        CustomerFavoriteWorker.objects.create(customer=other_customer, worker=self.worker)
        response = self.client.get(reverse('admin-schedule-workers', args=[self.schedule.id]), {'group': 'favorites'})
        self.assertEqual(response.status_code, 200, response.data)
        data = response.data['data']
        self.assertEqual(data['count'], 1)
        self.assertEqual(data['results'][0]['id'], worker.id)
        self.assertFalse(data['results'][0]['can_receive_invitation'])
        self.assertIn('Hồ sơ chưa được duyệt', data['results'][0]['unavailable_reasons'])

    def test_worker_tabs_reject_unknown_group(self):
        response = self.client.get(reverse('admin-schedule-workers', args=[self.schedule.id]), {'group': 'unknown'})
        self.assertEqual(response.status_code, 400)

    def test_all_worker_tabs_returns_union_without_pagination_or_duplicates(self):
        from apps.worker.models import CustomerFavoriteWorker
        favorite = self._additional_invitation_worker('union-favorite')
        requested = self._additional_invitation_worker('union-requested')
        unrelated = self._additional_invitation_worker('union-unrelated')
        CustomerFavoriteWorker.objects.create(customer=self.customer, worker=favorite)
        CustomerFavoriteWorker.objects.create(customer=self.customer, worker=requested)
        Wallet.objects.filter(user__in=[favorite, requested, unrelated]).update(balance=0)
        self.schedule.preferred_worker = requested
        self.schedule.save()
        response = self.client.get(reverse('admin-schedule-workers', args=[self.schedule.id]), {'group': 'all', 'page_size': 1})
        self.assertEqual(response.status_code, 200, response.data)
        workers = response.data['data']['results']
        self.assertEqual({worker['id'] for worker in workers}, {self.worker.id, favorite.id, requested.id})
        self.assertEqual(len(workers), 3)
        by_id = {worker['id']: worker for worker in workers}
        self.assertTrue(by_id[self.worker.id]['can_receive_invitation'])
        self.assertFalse(by_id[favorite.id]['can_receive_invitation'])
        self.assertEqual(by_id[requested.id]['unavailable_reasons'], ['Không đủ số dư'])
        self.assertTrue(by_id[requested.id]['is_customer_requested'])

    def test_accept_rechecks_cancelled_booking(self):
        invitation = self._invite().data['data']
        self.client.post(reverse('admin-booking-cancel', args=[self.booking.id]), {'reason': 'Khách hủy'}, format='json')
        self.client.force_authenticate(self.worker)
        response = self.client.post(reverse('worker-invitation-respond', args=[invitation['id']]), {'action': 'accept'}, format='json')
        self.assertEqual(response.status_code, 400, response.data)
        self.assertEqual(BookingAssignment.objects.get(pk=invitation['id']).status, 'CANCELLED')


    def test_other_session_customer_priority_does_not_block_admin_invitation(self):
        other = User.objects.create_user(username='priority-other', email='priority-other@example.com', role='WORKER')
        BookingSchedule.objects.create(booking=self.booking, sequence_no=2,
            scheduled_start=self.schedule.scheduled_start + timedelta(days=1), scheduled_end=self.schedule.scheduled_end + timedelta(days=1),
            preferred_worker=other, preferred_worker_expires_at=timezone.now() + timedelta(minutes=30))
        invitation = self._invite().data['data']
        self.client.force_authenticate(self.worker)
        detail = self.client.get(reverse('worker-booking-schedules', args=[self.booking.id]))
        self.assertEqual(len(detail.data['data']), 2)
        self.assertEqual(detail.data['data'][1]['claim_state'], 'TAKEN')
        response = self.client.post(reverse('worker-invitation-respond', args=[invitation['id']]), {'action': 'accept'}, format='json')
        self.assertEqual(response.status_code, 200, response.data)

    def _additional_invitation_worker(self, name='batch-worker'):
        worker = User.objects.create_user(username=name, email=f'{name}@example.com', role='WORKER')
        WorkerProfile.objects.create(user=worker, status='ACTIVE', registered_service=self.service)
        WorkerWorkingArea.objects.create(worker=worker, area=self.worker.working_areas.first().area)
        Wallet.objects.create(user=worker, balance=500000)
        return worker

    def _invite_workers(self, workers):
        self.client.force_authenticate(self.admin)
        return self.client.post(reverse('admin-schedule-bulk-assign'), {
            'booking_id': self.booking.id, 'schedule_ids': [self.schedule.id],
            'worker_ids': [worker.id for worker in workers], 'response_minutes': 30,
        }, format='json')

    def test_multi_invitation_each_recipient_can_see_and_first_accept_closes_others(self):
        from apps.notifications.models import Notification
        other = self._additional_invitation_worker()
        response = self._invite_workers([self.worker, other])
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(len(response.data['data']['assigned']), 2)
        detail = self.client.get(reverse('admin-booking-detail', args=[self.booking.id])).data['data']['schedules'][0]
        self.assertEqual(detail['invitation']['pending_count'], 2)
        self.assertEqual({w['id'] for w in detail['invitation']['workers']}, {self.worker.id, other.id})
        for worker in [self.worker, other]:
            self.client.force_authenticate(worker)
            available = self.client.get(reverse('worker-schedule-available'), {'booking_id': self.booking.id})
            self.assertTrue(available.data['data'])
            schedules = self.client.get(reverse('worker-booking-schedules', args=[self.booking.id])).data['data']
            self.assertEqual(schedules[0]['claim_state'], 'OPEN')
            self.assertEqual(schedules[0]['invitation']['id'], BookingAssignment.objects.get(schedule=self.schedule, worker=worker).id)
        other_invite = BookingAssignment.objects.get(schedule=self.schedule, worker=other)
        accepted = self.client.post(reverse('worker-invitation-respond', args=[other_invite.id]), {'action': 'accept'}, format='json')
        self.assertEqual(accepted.status_code, 200, accepted.data)
        self.assertEqual(BookingAssignment.objects.get(schedule=self.schedule, worker=self.worker).status, 'CANCELLED')
        self.assertEqual(BookingAssignment.objects.filter(schedule=self.schedule, status='ACCEPTED').count(), 1)
        self.assertTrue(Notification.objects.filter(user=self.worker, message__contains='đã có người nhận').exists())
        self.client.force_authenticate(self.worker)
        closed = BookingAssignment.objects.get(schedule=self.schedule, worker=self.worker)
        self.assertEqual(self.client.post(reverse('worker-invitation-respond', args=[closed.id]), {'action': 'accept'}, format='json').status_code, 400)

    def test_multi_invitation_decline_one_keeps_remaining_restricted_until_all_decline(self):
        other = self._additional_invitation_worker()
        outsider = self._additional_invitation_worker('outsider-worker')
        self.assertEqual(self._invite_workers([self.worker, other]).status_code, 201)
        for worker in [self.worker, other]:
            self.client.force_authenticate(worker)
            invitation = BookingAssignment.objects.get(schedule=self.schedule, worker=worker)
            self.assertEqual(self.client.post(reverse('worker-invitation-respond', args=[invitation.id]), {'action': 'decline'}, format='json').status_code, 200)
            if worker == self.worker:
                self.client.force_authenticate(outsider)
                self.assertEqual(self.client.post(reverse('worker-schedule-claim', args=[self.schedule.id]), {}, format='json').status_code, 400)
        self.client.force_authenticate(outsider)
        result = self.client.post(reverse('worker-schedule-claim', args=[self.schedule.id]), {}, format='json')
        self.assertEqual(result.status_code, 201, result.data)

    def test_multi_invitation_withdraw_closes_all(self):
        other = self._additional_invitation_worker()
        self.assertEqual(self._invite_workers([self.worker, other]).status_code, 201)
        result = self.client.post(reverse('admin-invitation-withdraw', args=[self.schedule.id]), {'reason': 'Đổi kế hoạch'}, format='json')
        self.assertEqual(result.status_code, 200, result.data)
        self.assertEqual(BookingAssignment.objects.filter(schedule=self.schedule, status='CANCELLED').count(), 2)
        self.assertFalse(BookingAssignment.objects.filter(schedule=self.schedule, status='PENDING').exists())

    def test_multi_invitation_invalid_recipient_does_not_send_partial_batch(self):
        other = self._additional_invitation_worker()
        Wallet.objects.filter(user=other).update(balance=0)
        result = self._invite_workers([self.worker, other])
        self.assertEqual(result.status_code, 400, result.data)
        self.assertFalse(BookingAssignment.objects.filter(schedule=self.schedule).exists())
        self.assertEqual(self._invite_workers([self.worker, self.worker]).status_code, 400)

    def test_multi_invitation_failed_accept_leaves_every_invitation_pending(self):
        other = self._additional_invitation_worker()
        self.assertEqual(self._invite_workers([self.worker, other]).status_code, 201)
        Wallet.objects.filter(user=other).update(balance=0)
        self.client.force_authenticate(other)
        invitation = BookingAssignment.objects.get(schedule=self.schedule, worker=other)
        result = self.client.post(reverse('worker-invitation-respond', args=[invitation.id]), {'action': 'accept'}, format='json')
        self.assertEqual(result.status_code, 400, result.data)
        self.assertEqual(BookingAssignment.objects.filter(schedule=self.schedule, status='PENDING').count(), 2)
