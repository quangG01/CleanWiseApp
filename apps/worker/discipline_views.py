from django.db import transaction
from django.db.models import Prefetch, Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.permissions import IsAdminRole, IsWorkerRole
from apps.complaints.models import Complaint, ComplaintIssueType

from . import discipline_service as service
from .models import BookingAssignment, WorkerDisciplineCase as Case
from .serializers import DisciplineDecisionSerializer


class CasePagination(PageNumberPagination):
    page_size = 20


def _cases():
    return Case.objects.select_related('assignment__schedule__booking', 'assignment__worker').prefetch_related(
        'appeals', Prefetch('assignment__schedule__complaints', queryset=service.open_worked_appeals(),
                            to_attr='open_worked_appeals'),
    )


def _case_data(case):
    schedule = case.assignment.schedule
    appeals = sorted(case.appeals.all(), key=lambda appeal: (appeal.created_at, appeal.pk), reverse=True)
    current = next((appeal for appeal in appeals if appeal.status != Complaint.Status.CANCELLED), None)
    visible_appeal = current
    if case.kind == Case.Kind.NO_SHOW and (not current or current.status not in service.OPEN_APPEALS):
        visible_appeal = next((appeal for appeal in schedule.open_worked_appeals
                               if appeal.reporter_id == case.assignment.worker_id), current)
    active_sanction = case.sanction == Case.Sanction.BANNED or (
        case.sanction_until and case.sanction_until > timezone.now()
    )
    return {
        'id': case.pk, 'worker': case.assignment.worker_id,
        'worker_name': case.assignment.worker.get_full_name() or case.assignment.worker.username,
        'booking': schedule.booking_id, 'booking_code': schedule.booking.booking_code,
        'schedule': schedule.pk, 'sequence': schedule.sequence_no,
        'kind': case.kind, 'kind_label': case.get_kind_display(),
        'status': case.status, 'status_label': case.get_status_display(),
        'deduction': case.deduction, 'reason': case.reason, 'review_note': case.review_note,
        'occurred_at': case.occurred_at, 'expires_at': case.occurred_at + service.WINDOW,
        'appeal_id': visible_appeal.pk if visible_appeal else None,
        'appeal_status': visible_appeal.status if visible_appeal else None,
        'can_appeal': service.can_appeal(case, current),
        'sanction': case.sanction if active_sanction else '', 'sanction_label': case.get_sanction_display(),
        'sanction_until': case.sanction_until, 'sanction_note': case.sanction_note,
    }


def _page(request, queryset):
    pagination = CasePagination()
    rows = pagination.paginate_queryset(queryset, request)
    return pagination.get_paginated_response([_case_data(case) for case in rows])


class MyDisciplineView(APIView):
    permission_classes = [IsWorkerRole]

    def get(self, request):
        response = _page(request, _cases().filter(assignment__worker=request.user))
        response.data['summary'] = service.summary(request.user.pk)
        response.data['appeal_issue_type'] = ComplaintIssueType.objects.filter(
            code=service.APPEAL_CODE, is_active=True,
        ).values_list('pk', flat=True).first()
        return response


class CancellationPreviewView(APIView):
    permission_classes = [IsWorkerRole]

    def get(self, request, assignment_id):
        assignment = get_object_or_404(
            BookingAssignment.objects.select_related('schedule'), pk=assignment_id,
            worker=request.user, status=BookingAssignment.Status.ACCEPTED,
        )
        return Response(service.cancellation_preview(assignment))


class AdminDisciplineView(APIView):
    permission_classes = [IsAdminRole]

    def get(self, request):
        cases = _cases()
        search = request.query_params.get('search', '').strip()
        if search:
            cases = cases.filter(
                Q(assignment__schedule__booking__booking_code__icontains=search)
                | Q(assignment__worker__username__icontains=search)
                | Q(assignment__worker__first_name__icontains=search)
                | Q(assignment__worker__last_name__icontains=search)
            )
        if request.query_params.get('pending') == 'true':
            cases = cases.filter(Q(status=Case.Status.PENDING) | Q(appeals__status__in=service.OPEN_APPEALS)
                                 | Q(sanction=Case.Sanction.PROPOSED, sanction_until__gt=timezone.now())).distinct()
        return _page(request, cases.order_by('assignment__worker_id', 'assignment__schedule__booking_id', '-occurred_at', '-pk'))


class AdminDisciplineDetailView(APIView):
    permission_classes = [IsAdminRole]

    def _detail(self, case, user):
        now = timezone.now()
        summary = service.summary(case.assignment.worker_id, now)
        worker_cases = service.worker_cases(case.assignment.worker_id)
        return {
            **_case_data(case), 'summary': summary,
            'can_apply_sanction': summary['enforced'] and summary['score'] == 0
            and case.status == Case.Status.CONFIRMED and case.occurred_at > now - service.WINDOW
            and not service._active_sanctions(worker_cases, now).exists()
            and not service.has_open_appeals(worker_cases, case.assignment.worker_id),
            'can_decide_proposal': bool(case.proposed_by_id and case.proposed_by_id != user.pk),
        }

    def get(self, request, pk):
        return Response(self._detail(get_object_or_404(_cases(), pk=pk), request.user))

    @transaction.atomic
    def post(self, request, pk):
        serializer = DisciplineDecisionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        case = service.lock_case(pk)
        action = serializer.validated_data['action']
        note = serializer.validated_data['note']
        now = timezone.now()
        if action in ('CONFIRM', 'WAIVE'):
            if service.has_open_appeals(Case.objects.filter(pk=pk), case.assignment.worker_id):
                raise serializers.ValidationError({'action': 'Vui lòng xử lý khiếu nại đang mở trước.'})
            if case.status == Case.Status.WAIVED or (action == 'CONFIRM' and case.status != Case.Status.PENDING):
                raise serializers.ValidationError({'action': 'Vi phạm đã được xử lý.'})
            service.review(case, actor=request.user, waive=action == 'WAIVE', note=note, now=now)
        else:
            service.decide_sanction(case, actor=request.user, action=action, note=note, now=now)
        return Response(self._detail(_cases().get(pk=pk), request.user))
