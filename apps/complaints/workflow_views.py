from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import transaction
from rest_framework import serializers
from rest_framework.generics import get_object_or_404
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.permissions import IsAdminRole, IsCustomerRole
from apps.notifications.realtime import push_complaint_changed
from apps.vouchers.models import Voucher

from . import workflow
from .models import Complaint, ComplaintProposal as Proposal
from .serializers import ComplaintDetailSerializer


class AdminWorkflowSerializer(serializers.Serializer):
    action = serializers.ChoiceField(
        choices=['CLAIM', 'ACK', 'REQUEST', 'VERIFY', 'OFFER', 'SCHEDULE_REDO', 'COMPLETE', 'REJECT'],
    )
    message = serializers.CharField(max_length=2000, required=False)
    basis = serializers.CharField(max_length=1000, required=False)
    reopen_instructions = serializers.CharField(max_length=500, required=False)
    next_update_at = serializers.DateTimeField(required=False)
    proposal_id = serializers.IntegerField(min_value=1, required=False)
    service_action = serializers.ChoiceField(choices=Proposal.ServiceAction.choices, required=False)
    scheduled_start = serializers.DateTimeField(required=False)
    worker = serializers.PrimaryKeyRelatedField(queryset=get_user_model().objects.all(), required=False)
    voucher = serializers.PrimaryKeyRelatedField(queryset=Voucher.objects.all(), required=False)
    refund_scope = serializers.ChoiceField(choices=Proposal.RefundScope.choices, required=False)
    refund_amount = serializers.DecimalField(max_digits=12, decimal_places=0, min_value=Decimal(1), required=False)
    cash_reference = serializers.CharField(max_length=150, required=False)
    recover_worker_earning = serializers.BooleanField(required=False)

    def validate(self, data):
        action = data['action']
        required = {
            'CLAIM': (), 'ACK': ('message',), 'REQUEST': ('message',), 'VERIFY': ('message',), 'OFFER': ('message',),
            'SCHEDULE_REDO': ('proposal_id',), 'COMPLETE': ('message', 'proposal_id'),
            'REJECT': ('message', 'basis', 'reopen_instructions'),
        }
        for field in required[action]:
            if field not in data:
                raise serializers.ValidationError({field: 'Vui lòng nhập thông tin này.'})
        return data


class CustomerWorkflowSerializer(serializers.Serializer):
    action = serializers.ChoiceField(choices=['REPLY', 'ACCEPT', 'REVISE', 'REOPEN'])
    message = serializers.CharField(max_length=2000, required=False)
    proposal_id = serializers.IntegerField(min_value=1, required=False)

    def validate(self, data):
        if data['action'] != 'ACCEPT' and not data.get('message'):
            raise serializers.ValidationError({'message': 'Vui lòng nhập nội dung phản hồi.'})
        return data


class AdminComplaintWorkflowView(APIView):
    permission_classes = [IsAdminRole]

    @transaction.atomic
    def post(self, request, pk):
        complaint = get_object_or_404(
            Complaint.objects.select_for_update(), pk=pk, reporter_role=Complaint.ReporterRole.CUSTOMER,
        )
        serializer = AdminWorkflowSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        workflow.handle_admin(complaint, request.user, serializer.validated_data)
        push_complaint_changed(complaint.pk)
        return Response(ComplaintDetailSerializer(complaint, context={'request': request}).data)


class CustomerComplaintWorkflowView(APIView):
    permission_classes = [IsCustomerRole]

    @transaction.atomic
    def post(self, request, pk):
        complaint = get_object_or_404(
            Complaint.objects.select_for_update(), pk=pk, reporter=request.user,
            reporter_role=Complaint.ReporterRole.CUSTOMER,
        )
        serializer = CustomerWorkflowSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        workflow.handle_customer(complaint, request.user, serializer.validated_data)
        push_complaint_changed(complaint.pk)
        return Response(ComplaintDetailSerializer(complaint, context={'request': request}).data)
