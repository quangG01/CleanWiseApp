from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.addresses.models import CustomerAddress
from apps.authentication.models import WorkerProfile
from apps.bookings.models import Booking, BookingSchedule
from apps.complaints.models import ComplaintIssueType
from apps.services.models import Service

from . import assignment_service, discipline_service
from .models import BookingAssignment, WorkerDisciplineCase as Case


@override_settings(WORKER_DISCIPLINE_ENFORCED=True)
class DisciplineTests(APITestCase):
    def setUp(self):
        user = get_user_model()
        self.worker = user.objects.create_user(username='worker', email='worker@test.example', role='WORKER')
        self.customer = user.objects.create_user(username='customer', email='customer@test.example', role='CUSTOMER')
        self.admin = user.objects.create_user(username='admin', email='admin@test.example', role='ADMIN')
        self.other_admin = user.objects.create_user(username='reviewer', email='reviewer@test.example', role='ADMIN')
        address = CustomerAddress.objects.create(customer=self.customer, address_line='Test', city='TP.HCM', ward='Test')
        service = Service.objects.create(code='TEST_DISCIPLINE', name='Dọn nhà', section_code='HOME_CLEANING',
                                         form_schema={}, pricing_config={})
        WorkerProfile.objects.create(user=self.worker, registered_service=service, status='ACTIVE')
        self.booking = Booking.objects.create(booking_code='BK-DISCIPLINE', customer=self.customer,
                                              address=address, service=service, service_data={})
        self.issue = ComplaintIssueType.objects.create(code=discipline_service.APPEAL_CODE,
                                                       name='Xem xét điểm tín nhiệm', applies_to='WORKER')

    def assignment(self, hours):
        start = timezone.now() + timedelta(hours=hours)
        schedule = BookingSchedule.objects.create(booking=self.booking,
                                                  sequence_no=self.booking.schedules.count() + 1,
                                                  scheduled_start=start, scheduled_end=start + timedelta(hours=2))
        return BookingAssignment.objects.create(schedule=schedule, worker=self.worker, status='ACCEPTED')

    def cancel(self, assignment, *, late=False, **kwargs):
        return self.client.post(reverse('worker-assignment-report-absence' if late else 'worker-assignment-cancel',
                                        args=[assignment.pk]), {'reason': 'Việc đột xuất', **kwargs})

    def decide(self, case, action):
        return self.client.post(reverse('admin-discipline-detail', args=[case.pk]),
                                {'action': action, 'note': 'Đã xác minh thông tin.'})

    def test_cancel_from_ten_restores_after_30_days_and_retries_once(self):
        self.client.force_authenticate(self.worker)
        item = self.assignment(10)
        url = reverse('worker-cancel-preview', args=[item.pk])
        preview = self.client.get(url).json()['data']
        self.assertEqual((preview['score'], preview['deduction'], preview['projected_score']), (10, 2, 8))
        self.assertEqual(self.cancel(item, expected_deduction=1, expected_score=9).status_code, 400)
        self.assertEqual(self.cancel(item, expected_deduction=2, expected_score=8).status_code, 200)
        self.assertEqual(self.cancel(item, expected_deduction=2, expected_score=8).status_code, 200)
        case = Case.objects.get(assignment=item)
        self.assertEqual(discipline_service.summary(self.worker.pk)['score'], 8)
        self.assertEqual(discipline_service.summary(self.worker.pk, case.occurred_at + timedelta(days=30))['score'], 10)

    def test_late_and_no_show_only_deduct_after_review(self):
        self.client.force_authenticate(self.worker)
        late = self.assignment(3)
        self.assertEqual(self.cancel(late).status_code, 400)
        self.assertEqual(self.cancel(late, late=True).status_code, 200)
        missed = self.assignment(-2)
        assignment_service.handle_missed_checkins()
        late_case = Case.objects.get(assignment=late)
        missed_case = Case.objects.get(assignment=missed)
        self.assertEqual((late_case.status, missed_case.status), ('PENDING', 'PENDING'))
        self.assertEqual(discipline_service.summary(self.worker.pk)['score'], 10)
        self.client.force_authenticate(self.admin)
        self.assertEqual(self.decide(late_case, 'CONFIRM').status_code, 200)
        self.assertEqual(self.decide(missed_case, 'CONFIRM').status_code, 200)
        state = discipline_service.summary(self.worker.pk)
        missed_case.refresh_from_db()
        self.assertEqual(state['score'], 3)
        self.assertEqual(state['restricted_until'], missed_case.confirmed_at + timedelta(hours=72))

    def test_restriction_blocks_all_claim_paths_and_accepted_appeal_restores_access(self):
        self.client.force_authenticate(self.worker)
        items = [self.assignment(10 + index) for index in range(3)]
        for item in items:
            self.assertEqual(self.cancel(item).status_code, 200)
        case = Case.objects.get(assignment=items[-1])
        blocked = self.assignment(48)
        blocked.status = 'PENDING'
        blocked.assigned_by = self.admin
        blocked.expired_at = timezone.now() + timedelta(minutes=15)
        blocked.save()
        claim_urls = [
            ('worker-schedule-claim', blocked.schedule_id, {}),
            ('worker-booking-claim-package', self.booking.pk, {'schedule_ids': [blocked.schedule_id]}),
            ('worker-invitation-respond', blocked.pk, {'action': 'accept'}),
        ]
        for name, pk, body in claim_urls:
            response = self.client.post(reverse(name, args=[pk]), body, format='json')
            self.assertEqual(response.status_code, 400, response.data)
            self.assertIn('discipline', response.json()['errors'])
        self.assertEqual(discipline_service.summary(self.worker.pk)['restricted_until'], case.confirmed_at + timedelta(hours=24))
        appeal = self.client.post(reverse('worker-complaint-list-create'), {
            'booking': self.booking.pk, 'schedule': case.assignment.schedule_id, 'issue_type': self.issue.pk,
            'discipline_case': case.pk, 'content': 'Xin kiểm tra lý do hủy.',
        })
        self.assertEqual(appeal.status_code, 201, appeal.data)
        self.client.force_authenticate(self.admin)
        response = self.client.post(reverse('admin-complaint-resolve', args=[appeal.json()['data']['id']]), {
            'status': 'RESOLVED', 'resolution_note': 'Chấp nhận giải trình.',
        })
        self.assertEqual(response.status_code, 200, response.data)
        state = discipline_service.summary(self.worker.pk)
        self.assertEqual(state['score'], 6)
        self.assertTrue(state['can_claim'])

    def test_ban_needs_two_admins_and_waiver_can_remove_it(self):
        self.client.force_authenticate(self.worker)
        cases = []
        for index in range(5):
            assignment = self.assignment(10 + index)
            self.assertEqual(self.cancel(assignment).status_code, 200)
            cases.append(Case.objects.get(assignment=assignment))
        latest = cases[-1]
        self.client.force_authenticate(self.admin)
        self.assertEqual(self.decide(latest, 'PROPOSE_BAN').status_code, 200)
        self.assertEqual(self.decide(latest, 'APPROVE_BAN').status_code, 400)
        self.client.force_authenticate(self.other_admin)
        self.assertEqual(self.decide(latest, 'APPROVE_BAN').status_code, 200)
        self.assertEqual(discipline_service.summary(self.worker.pk)['status'], 'BANNED')
        self.assertEqual(self.decide(cases[0], 'WAIVE').status_code, 200)
        state = discipline_service.summary(self.worker.pk)
        self.assertEqual((state['score'], state['status']), (2, 'RESTRICTED'))

    def test_open_worked_complaint_blocks_no_show_confirmation(self):
        missed = self.assignment(-2)
        assignment_service.handle_missed_checkins()
        missed.schedule.status = BookingSchedule.Status.MISSED
        missed.schedule.save(update_fields=['status'])
        case = Case.objects.get(assignment=missed)
        issue = ComplaintIssueType.objects.create(code='AUTO_CANCELLED_WORKED', name='Đã thực hiện buổi làm',
                                                  stage='AFTER_SERVICE', applies_to='WORKER')
        self.client.force_authenticate(self.worker)
        response = self.client.post(reverse('worker-complaint-list-create'), {
            'booking': self.booking.pk, 'schedule': missed.schedule_id,
            'issue_type': issue.pk, 'content': 'Tôi đã làm nhưng chưa check-in.',
        })
        self.assertEqual(response.status_code, 201, response.data)
        self.client.force_authenticate(self.admin)
        detail = self.client.get(reverse('admin-discipline-detail', args=[case.pk])).json()['data']
        self.assertEqual(detail['appeal_id'], response.json()['data']['id'])
        self.assertEqual(self.decide(case, 'CONFIRM').status_code, 400)
        self.assertEqual(discipline_service.summary(self.worker.pk)['score'], 10)

    @override_settings(WORKER_DISCIPLINE_ENFORCED=False)
    def test_tracking_mode_does_not_block_claims(self):
        self.client.force_authenticate(self.worker)
        for index in range(3):
            self.assertEqual(self.cancel(self.assignment(10 + index)).status_code, 200)
        state = discipline_service.summary(self.worker.pk)
        self.assertEqual(state['score'], 4)
        self.assertTrue(state['can_claim'])
