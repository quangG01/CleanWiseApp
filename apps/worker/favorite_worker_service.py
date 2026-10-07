from django.contrib.auth import get_user_model
from django.db import transaction
from rest_framework.exceptions import NotFound, PermissionDenied

from apps.authentication.models import WorkerProfile
from .models import BookingAssignment, CustomerFavoriteWorker
from apps.addresses.models import CustomerAddress
from apps.services.models import Service

from . import assignment_service

User = get_user_model()


def _get_active_worker(worker_id):
    try:
        return (
            User.objects
            .select_related('worker_profile')
            .get(
                pk=worker_id,
                role=User.Role.WORKER,
                worker_profile__status=WorkerProfile.Status.ACTIVE,
            )
        )
    except User.DoesNotExist as exc:
        raise NotFound('Không tìm thấy nhân viên đang hoạt động.') from exc


def _ensure_customer_has_assignment(customer, worker):
    has_assignment = BookingAssignment.objects.filter(
        worker=worker,
        status=BookingAssignment.Status.ACCEPTED,
        schedule__booking__customer=customer,
    ).exists()
    if not has_assignment:
        raise PermissionDenied(
            'Bạn chỉ có thể yêu thích nhân viên đã được phân công cho đơn của mình.'
        )


def get_worker_for_customer(*, customer, worker_id):
    worker = _get_active_worker(worker_id)
    _ensure_customer_has_assignment(customer, worker)
    return worker


def list_favorite_workers(*, customer, service_id=None, address_id=None):
    queryset = (
        CustomerFavoriteWorker.objects
        .filter(
            customer=customer,
            worker__role=User.Role.WORKER,
            worker__worker_profile__status=WorkerProfile.Status.ACTIVE,
        )
        .select_related('worker', 'worker__worker_profile')
        .order_by('-created_at', '-id')
    )
    if not service_id and not address_id:
        return queryset

    if service_id:
        section_code = (
            Service.objects.filter(pk=service_id)
            .values_list('section_code', flat=True).first()
        )
        if section_code is None:
            return queryset.none()
        queryset = queryset.filter(
            worker__worker_profile__registered_service__section_code=section_code,
        )

    if address_id:
        address = CustomerAddress.objects.filter(
            pk=address_id, customer=customer, is_active=True,
        ).first()
        if address is None:
            return queryset.none()
        return [
            fav for fav in queryset
            if assignment_service._covers(
                assignment_service._worker_area_index(fav.worker), address,
            )
        ]
    return queryset


@transaction.atomic
def add_favorite_worker(*, customer, worker_id):
    worker = _get_active_worker(worker_id)
    _ensure_customer_has_assignment(customer, worker)
    favorite, created = CustomerFavoriteWorker.objects.get_or_create(
        customer=customer,
        worker=worker,
    )
    return favorite, created


@transaction.atomic
def remove_favorite_worker(*, customer, worker_id):
    deleted_count, _ = CustomerFavoriteWorker.objects.filter(
        customer=customer,
        worker_id=worker_id,
    ).delete()
    return deleted_count > 0
