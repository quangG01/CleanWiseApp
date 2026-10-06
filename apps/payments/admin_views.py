from django.db.models import Q, Sum
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.permissions import IsAdminRole
from .models import Payment


class AdminPaymentPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100


def _row(p):
    customer = p.customer
    booking = p.booking
    return {
        'id': p.id,
        'booking': p.booking_id,
        # Sửa tên field cho đúng model Booking của bạn nếu khác
        'booking_code': getattr(booking, 'booking_code', None) or getattr(booking, 'code', None),
        'customer_name': (customer.get_full_name() or customer.username),
        'amount': str(p.amount),
        'method': p.method,
        'method_label': p.get_method_display(),
        'status': p.status,
        'status_label': p.get_status_display(),
        'transaction_code': p.transaction_code,
        'order_code': p.order_code,
        'failure_reason': p.failure_reason,
        'paid_at': p.paid_at,
        'created_at': p.created_at,
    }


class AdminPaymentListView(APIView):
    """GET /api/admin/payments/?status=&method=&search=&page=&page_size="""
    permission_classes = [IsAdminRole]

    def get(self, request):
        qs = Payment.objects.select_related('customer', 'booking')

        status_f = request.query_params.get('status')
        method_f = request.query_params.get('method')
        search = (request.query_params.get('search') or '').strip()

        if status_f:
            qs = qs.filter(status=status_f)
        if method_f:
            qs = qs.filter(method=method_f)
        if search:
            q = Q(transaction_code__icontains=search) | Q(customer__username__icontains=search)
            if search.isdigit():
                q |= Q(order_code=int(search)) | Q(booking_id=int(search))
            qs = qs.filter(q)

        paginator = AdminPaymentPagination()
        page = paginator.paginate_queryset(qs, request, view=self)

        success_total = Payment.objects.filter(status=Payment.Status.SUCCESS).aggregate(s=Sum('amount'))['s'] or 0

        return Response({'data': {
            'results': [_row(p) for p in page],
            'count': paginator.page.paginator.count,
            'page': paginator.page.number,
            'total_pages': paginator.page.paginator.num_pages,
            'has_next': paginator.page.has_next(),
            'summary': {
                'success_total': str(success_total),
                'pending': Payment.objects.filter(status=Payment.Status.PENDING).count(),
                'failed': Payment.objects.filter(status=Payment.Status.FAILED).count(),
            },
        }})