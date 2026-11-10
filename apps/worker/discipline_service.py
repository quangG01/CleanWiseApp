from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.authentication.models import WorkerProfile
from apps.bookings.activity_service import record_booking_activity
from apps.bookings.models import Booking, BookingActivity, BookingSchedule

from .constants import MIN_CANCEL_HOURS, WORKED_AUTO_CANCELLED_CODE
from .models import WorkerDisciplineCase as Case

WINDOW = timedelta(days=30)
APPEAL_CODE = 'WORKER_DISCIPLINE'
OPEN_APPEALS = ('PENDING', 'IN_REVIEW')


def enforced():
    return getattr(settings, 'WORKER_DISCIPLINE_ENFORCED', False)


def lock_worker(worker_id):
    # Assignment workflows lock the booking before taking this lock.
    WorkerProfile.objects.select_for_update().filter(user_id=worker_id).first()


def worker_cases(worker_id):
    return Case.objects.filter(assignment__worker_id=worker_id)


def can_appeal(case, latest):
    if case.status == Case.Status.WAIVED:
        return False
    if latest is None:
        return True
    return bool(
        latest.status not in OPEN_APPEALS
        and case.sanction in (Case.Sanction.SUSPENDED, Case.Sanction.BANNED)
        and case.sanction_at and latest.created_at < case.sanction_at
    )


def open_worked_appeals():
    from apps.complaints.models import Complaint

    return Complaint.objects.filter(issue_type__code=WORKED_AUTO_CANCELLED_CODE, status__in=OPEN_APPEALS)


def has_open_appeals(cases, worker_id):
    missed_schedules = cases.filter(kind=Case.Kind.NO_SHOW).values('assignment__schedule_id')
    return cases.filter(appeals__status__in=OPEN_APPEALS).exists() or open_worked_appeals().filter(
        reporter_id=worker_id, schedule_id__in=missed_schedules,
    ).exists()


def _score(cases, at):
    deductions = sum(
        case.deduction for case in cases
        if at - WINDOW < case.occurred_at <= at and case.confirmed_at <= at
    )
    return max(0, 10 - deductions)


def _hours(score):
    return 72 if score <= 3 else 24 if score <= 5 else 0


def _confirmed(cases):
    return cases.filter(status=Case.Status.CONFIRMED, confirmed_at__isnull=False)


def _active_sanctions(cases, now):
    return cases.filter(
        Q(sanction=Case.Sanction.BANNED)
        | Q(sanction__in=[Case.Sanction.SUSPENDED, Case.Sanction.PROPOSED], sanction_until__gt=now)
    )


def summary(worker_id, now=None):
    now = now or timezone.now()
    cases = worker_cases(worker_id)
    recent = list(_confirmed(cases).filter(occurred_at__gt=now - WINDOW - timedelta(hours=72)))
    score = _score(recent, now)
    deadlines = [
        case.confirmed_at + timedelta(hours=_hours(_score(recent, case.confirmed_at)))
        for case in recent if now - timedelta(hours=72) < case.confirmed_at <= now
        and case.occurred_at > case.confirmed_at - WINDOW
    ]
    until = max((deadline for deadline in deadlines if deadline > now), default=None)
    sanction = _active_sanctions(cases, now).order_by('-sanction_at', '-pk').first()
    status = 'WARNING' if score <= 7 else 'ACTIVE'
    if until:
        status = 'RESTRICTED'
    if score == 0:
        status = 'REVIEW'
    if sanction and sanction.sanction in (Case.Sanction.BANNED, Case.Sanction.SUSPENDED):
        status = sanction.sanction
        until = sanction.sanction_until
    active = enforced()
    return {
        'score': score, 'max_score': 10, 'status': status, 'restricted_until': until,
        'enforced': active,
        'can_claim': not active or (until is None and status != Case.Sanction.BANNED),
    }


def ensure_can_claim(worker_id, *, lock=False):
    if not enforced():
        return
    if lock:
        lock_worker(worker_id)
    state = summary(worker_id)
    if state['can_claim']:
        return
    if state['status'] == Case.Sanction.BANNED:
        message = 'Hồ sơ nhân viên đã bị cấm nhận việc. Xem Điểm và xử lý trong Khiếu nại của tôi.'
    else:
        until = timezone.localtime(state['restricted_until'])
        message = f'Bạn có thể nhận việc lại từ {until:%H:%M %d/%m/%Y}. Xem Điểm và xử lý trong Khiếu nại của tôi.'
    raise ValidationError({'discipline': message})


def cancellation_preview(assignment, now=None):
    now = now or timezone.now()
    remaining = assignment.schedule.scheduled_start - now
    pending = assignment.schedule.status == BookingSchedule.Status.PENDING
    can_cancel = pending and remaining >= timedelta(hours=MIN_CANCEL_HOURS)
    late = pending and timedelta(0) < remaining < timedelta(hours=MIN_CANCEL_HOURS)
    deduction = 3 if late else 1 if remaining >= timedelta(hours=24) else 2
    state = summary(assignment.worker_id, now)
    projected = max(0, state['score'] - deduction)
    return {
        **state, 'deduction': deduction, 'projected_score': projected,
        'restriction_hours': _hours(projected), 'requires_review': late, 'can_cancel': can_cancel,
    }


def _notify(case, title, message):
    from apps.notifications.services import create_notification_with_push

    transaction.on_commit(lambda: create_notification_with_push(
        user=case.assignment.worker, title=title, message=message,
        related_booking=case.assignment.schedule.booking,
    ), robust=True)


def _audit(case, actor, action, note):
    schedule = case.assignment.schedule
    record_booking_activity(
        booking=schedule.booking, schedule=schedule, actor=actor,
        event_type=BookingActivity.EventType.BOOKING_UPDATED,
        message=f'Xử lý điểm tín nhiệm của buổi {schedule.sequence_no}.',
        metadata={'discipline_case': case.pk, 'decision': action, 'reason': note},
    )


def record_cancellation(assignment, *, reason, late, now, deduction):
    case, created = Case.objects.get_or_create(assignment=assignment, defaults={
        'kind': Case.Kind.LATE if late else Case.Kind.CANCEL,
        'deduction': deduction, 'occurred_at': now, 'reason': reason,
        'status': Case.Status.PENDING if late else Case.Status.CONFIRMED,
        'confirmed_at': None if late else now,
    })
    if created and not late:
        state = summary(assignment.worker_id, now)
        message = f'Buổi đã hủy bị trừ {case.deduction} điểm. Điểm hiện tại: {state["score"]}/10.'
        if state['enforced'] and not state['can_claim'] and state['restricted_until']:
            until = timezone.localtime(state['restricted_until'])
            message += f' Tạm dừng nhận việc mới đến {until:%H:%M %d/%m/%Y}.'
        elif state['score'] <= 7:
            message += ' Xem quy định và lịch sử trong mục Khiếu nại của tôi.'
        _notify(case, 'Điểm tín nhiệm đã thay đổi',
                message)
    return case


def record_missed(assignment, now):
    Case.objects.get_or_create(assignment=assignment, defaults={
        'kind': Case.Kind.NO_SHOW, 'deduction': 4, 'occurred_at': now,
        'reason': assignment.response_note or '',
    })


def lock_case(case_id):
    ref = get_object_or_404(Case.objects.select_related('assignment__schedule'), pk=case_id)
    Booking.objects.select_for_update().get(pk=ref.assignment.schedule.booking_id)
    lock_worker(ref.assignment.worker_id)
    return Case.objects.select_for_update(of=('self',)).select_related(
        'assignment__worker', 'assignment__schedule__booking',
    ).get(pk=case_id)


def _revoke_unsupported_sanctions(worker_id, now):
    cases = worker_cases(worker_id)
    remaining = list(_confirmed(cases))
    revoked = []
    for case in _active_sanctions(cases, now).select_related('assignment__schedule__booking', 'assignment__worker'):
        if case.status == Case.Status.CONFIRMED and _score(remaining, case.sanction_at) == 0:
            continue
        case.sanction = Case.Sanction.NONE
        case.sanction_until = None
        case.save(update_fields=['sanction', 'sanction_until'])
        revoked.append(case.pk)
        _notify(case, 'Đã gỡ xử lý hồ sơ', 'CleanWise đã tính lại điểm sau khi miễn vi phạm.')
    return revoked


def review(case, *, actor, waive, note, now):
    case.reviewed_at = now
    case.review_note = note
    if waive:
        case.status = Case.Status.WAIVED
    elif case.status == Case.Status.PENDING:
        case.status = Case.Status.CONFIRMED
        case.confirmed_at = now
    case.save(update_fields=['status', 'confirmed_at', 'reviewed_at', 'review_note'])
    audit_note = note
    if waive:
        revoked = _revoke_unsupported_sanctions(case.assignment.worker_id, now)
        if revoked:
            audit_note += f' Đã gỡ xử lý hồ sơ ở các vụ {revoked}.'
    _audit(case, actor, 'WAIVE' if waive else 'CONFIRM', audit_note)
    state = summary(case.assignment.worker_id, now)
    _notify(case, 'Đã xem xét điểm tín nhiệm', f'{note} Điểm hiện tại: {state["score"]}/10.')


def decide_sanction(case, *, actor, action, note, now):
    if not enforced():
        raise ValidationError({'action': 'Đang chạy chế độ theo dõi. Chưa áp dụng xử lý hồ sơ.'})
    worker_id = case.assignment.worker_id
    cases = worker_cases(worker_id)
    if action in ('APPROVE_BAN', 'REJECT_BAN'):
        if case.sanction != Case.Sanction.PROPOSED or case.sanction_until <= now or case.proposed_by_id == actor.pk:
            raise ValidationError({'action': 'Cần một quản trị viên khác xử lý đề xuất cấm đang mở.'})
    elif _active_sanctions(cases, now).exists():
        raise ValidationError({'action': 'Hồ sơ đang có một quyết định xử lý khác.'})

    if action != 'REJECT_BAN' and (
        case.status != Case.Status.CONFIRMED or case.occurred_at <= now - WINDOW
        or summary(worker_id, now)['score'] != 0
        or has_open_appeals(cases, worker_id)
    ):
        raise ValidationError({'action': 'Cần 0/10 điểm và xử lý xong khiếu nại trước khi khóa hoặc cấm hồ sơ.'})

    sanctions = {
        'SUSPEND': Case.Sanction.SUSPENDED, 'PROPOSE_BAN': Case.Sanction.PROPOSED,
        'APPROVE_BAN': Case.Sanction.BANNED, 'REJECT_BAN': Case.Sanction.NONE,
    }
    case.sanction = sanctions[action]
    case.sanction_at = now
    case.sanction_note = note
    duration = {'SUSPEND': timedelta(days=7), 'PROPOSE_BAN': timedelta(hours=72)}.get(action)
    case.sanction_until = now + duration if duration else None
    if action == 'PROPOSE_BAN':
        case.proposed_by = actor
    case.save(update_fields=['sanction', 'sanction_at', 'sanction_note', 'sanction_until', 'proposed_by'])
    _audit(case, actor, action, note)
    if action in ('SUSPEND', 'APPROVE_BAN'):
        _notify(case, case.get_sanction_display(), note)
