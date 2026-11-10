"""Add isolated, repeatable dashboard fixtures without sending notifications."""
import calendar
from datetime import datetime, time, timedelta
from decimal import Decimal

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.addresses.models import CustomerAddress
from apps.authentication.models import WorkerProfile
from apps.bookings.models import Booking, BookingSchedule
from apps.reviews.models import Review
from apps.services.models import Service
from apps.vouchers.models import Voucher
from apps.vouchers.voucher_service import assign_voucher_to_customer
from apps.wallets.models import WorkerEarning
from apps.worker.models import BookingAssignment, CustomerFavoriteWorker, WorkerFavoriteMonthlyEntry
from apps.analytics.models import MonthlyVipReward
from apps.analytics.report_service import ZONE


class Command(BaseCommand):
    help = 'Sinh dữ liệu thử cho 7 trang thống kê; tài khoản cw_hub_demo_, đơn CW-HUB-. Chỉ DEBUG.'

    def add_arguments(self, parser):
        parser.add_argument('--date', help='Ngày neo YYYY-MM-DD, mặc định hôm nay giờ Việt Nam.')
        parser.add_argument('--months', type=int, default=3)

    @transaction.atomic
    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError('Chỉ sinh dữ liệu mẫu khi DEBUG=True.')
        now = timezone.now()
        today = timezone.localdate(timezone=ZONE)
        try:
            anchor = datetime.strptime(options['date'], '%Y-%m-%d').date() if options['date'] else today
        except ValueError as exc:
            raise CommandError('--date phải có dạng YYYY-MM-DD.') from exc
        if anchor > today or not 2000 <= anchor.year <= 2100 or not 1 <= options['months'] <= 12:
            raise CommandError('Ngày neo phải từ 2000–2100, không ở tương lai; --months từ 1–12.')
        User = get_user_model()

        def account(role, index, name):
            username = f'cw_hub_demo_{role.lower()}_{index:02}'
            email = f'{username}@cleanwise.test'
            user, created = User.objects.get_or_create(username=username, defaults={
                'email': email, 'role': role, 'first_name': name, 'is_active': True,
            })
            if user.email != email or user.role != role:
                raise CommandError(f'Tài khoản {username} trùng dữ liệu khác; dừng để tránh sửa dữ liệu thật.')
            if created:
                user.set_unusable_password()
                user.save(update_fields=['password'])
            return user

        customers = [account('CUSTOMER', i+1, n) for i,n in enumerate([
            'Nguyễn Minh Anh · Mẫu', 'Trần Hoàng Nam · Mẫu', 'Lê Thu Hà · Mẫu', 'Phạm Ngọc Linh · Mẫu',
            'Võ Quốc Bảo · Mẫu', 'Nguyễn Bảo Ngọc · Mẫu', 'Trần Gia Huy · Mẫu', 'Lê Hoài An · Mẫu',
            'Phạm Minh Khang · Mẫu', 'Đỗ Thanh Trúc · Mẫu', 'Vũ Anh Thư · Mẫu', 'Bùi Thanh Tâm · Mẫu',
        ])]
        workers = [account('WORKER', i+1, n) for i,n in enumerate([
            'Nguyễn Thị Lan · Mẫu', 'Trần Minh Tuấn · Mẫu', 'Lê Thanh Hương · Mẫu', 'Phạm Thị Hoa · Mẫu',
            'Võ Thanh Tâm · Mẫu', 'Bùi Thị Lan · Mẫu', 'Đỗ Quang Huy · Mẫu', 'Lê Ngọc Hân · Mẫu',
        ])]
        services = []
        for index, name in enumerate(['Dọn nhà', 'Vệ sinh máy lạnh', 'Vệ sinh sofa']):
            service, created = Service.objects.get_or_create(code=f'CW_HUB_DEMO_{index+1}', defaults={
                'section_code': 'HOME_CLEANING', 'name': f'{name} · Mẫu thống kê',
                'description': 'Dữ liệu thử thống kê CleanWise, không dùng đặt lịch thực tế.',
                'form_schema': {}, 'pricing_config': {},
            })
            if not created and 'Mẫu thống kê' not in service.name:
                raise CommandError('Mã dịch vụ mẫu đã được dùng cho dịch vụ khác.')
            services.append(service)
        for i, worker in enumerate(workers):
            profile, created = WorkerProfile.objects.get_or_create(user=worker, defaults={'status': 'DRAFT'})
            if created:
                WorkerProfile.objects.filter(pk=profile.pk).update(status='ACTIVE', registered_service=services[i%3])
        addresses = []
        for customer in customers:
            address, _ = CustomerAddress.objects.get_or_create(customer=customer, address_line='123 Đường Mẫu Thống Kê', defaults={
                'receiver_name': customer.first_name, 'receiver_phone': '0900000000', 'city': 'TP Hồ Chí Minh',
            })
            addresses.append(address)

        created_orders = created_earnings = created_favorites = 0
        periods = []
        for offset in range(options['months']):
            year, month_index = divmod(anchor.year*12+anchor.month-1-offset,12)
            first = anchor.replace(year=year,month=month_index+1,day=1)
            periods.append(first)
            max_day = anchor.day if offset==0 else calendar.monthrange(first.year, first.month)[1]
            counts = [12,10,9,8,6,5,4,3,2,1,1,1]
            for ci, customer in enumerate(customers):
                volume = max(1, counts[ci]-offset)
                for index in range(volume+1):
                    code = f'CW-HUB-{first:%y%m}-{ci+1:02}-{index+1:02}'
                    if Booking.objects.filter(booking_code=code).exists():
                        continue
                    extra = index==volume
                    status = (['PENDING','CANCELLED','COMPLETED'][ci%3] if extra else 'COMPLETED')
                    payment_status = ('REFUNDED' if ci%3==2 else 'UNPAID') if extra else 'PAID'
                    created_at = min(datetime.combine(first.replace(day=1+(index*3+ci)%max_day), time.min, tzinfo=ZONE),now)
                    end = min(created_at+timedelta(hours=2),now)
                    amount = Decimal(250000 + (ci%4)*50000 + (index%3)*20000)
                    booking = Booking(booking_code=code, customer=customer, service=services[(ci+index)%3],
                        address=addresses[ci], service_data={}, status=status, payment_status=payment_status,
                        total_amount=amount, subtotal_amount=amount, refunded_amount=amount if payment_status=='REFUNDED' else 0,
                        note='Dữ liệu thử thống kê CW-HUB; không thay đổi ví, không tạo thanh toán thật.')
                    Booking.objects.bulk_create([booking])
                    Booking.objects.filter(pk=booking.pk).update(created_at=created_at)
                    done = status=='COMPLETED'
                    # One explicit missing-end case and several missing-ledger cases per month.
                    missing_end = extra and ci==2
                    schedule = BookingSchedule(booking=booking,sequence_no=1,status='COMPLETED' if done else 'CANCELLED' if status=='CANCELLED' else 'PENDING',
                        scheduled_start=created_at,scheduled_end=created_at+timedelta(hours=2),
                        actual_start=created_at if done else None,actual_end=end if done and not missing_end else None)
                    BookingSchedule.objects.bulk_create([schedule])
                    worker = workers[(ci+index)%len(workers)]
                    assignment = BookingAssignment(schedule=schedule,worker=worker,status='ACCEPTED' if status!='CANCELLED' else 'CANCELLED',responded_at=created_at)
                    BookingAssignment.objects.bulk_create([assignment])
                    if done and not missing_end and not (ci==7 and index==0):
                        cash = index%3==0
                        commission = amount*Decimal('.10')
                        WorkerEarning.objects.bulk_create([WorkerEarning(worker=worker,booking=booking,schedule=schedule,
                            payment_method='CASH' if cash else 'ONLINE',gross_amount=amount,commission_rate='.10',
                            commission_amount=commission,worker_amount=amount-commission,completed_at=end,
                            settled_at=end if cash and index%2 else None)])
                        review=Review(assignment=assignment,rating=3+(ci+index)%3,comment='Đánh giá mẫu thống kê',is_visible=True)
                        Review.objects.bulk_create([review])
                        Review.objects.filter(pk=review.pk).update(created_at=end)
                        created_earnings+=1
                    created_orders+=1
            for wi,worker in enumerate(workers):
                volume = 3 + (wi*3+first.month)%10
                for ci in range(volume):
                    customer=customers[ci%len(customers)]
                    entry, created = WorkerFavoriteMonthlyEntry.objects.get_or_create(customer=customer,worker=worker,month=first,
                        defaults={'source':'DEMO','first_favorited_at':datetime.combine(first,time.min,tzinfo=ZONE)})
                    created_favorites+=int(created)
                    if offset==0:
                        CustomerFavoriteWorker.objects.get_or_create(customer=customer,worker=worker)

        vouchers=[]
        for amount in [50000,100000]:
            code=f'CW-HUB-VIP-{amount//1000}K'
            voucher,created=Voucher.objects.get_or_create(code=code,defaults={
                'name':f'Tri ân VIP mẫu · {amount//1000}K','description':'Voucher mẫu thống kê CW-HUB',
                'distribution_type':'ASSIGNED','discount_type':'FIXED','discount_value':amount,
                'min_order_amount':300000 if amount==50000 else 500000,'issuance_limit':500,
                'start_at':now-timedelta(days=1),'end_at':now+timedelta(days=45),'is_active':True,
            })
            if not created and voucher.description!='Voucher mẫu thống kê CW-HUB':
                raise CommandError(f'Mã voucher {code} đã tồn tại với mục đích khác.')
            vouchers.append(voucher)
        admin=User.objects.filter(role='ADMIN',is_active=True).first()
        if admin:
            for month in periods:
                customer=customers[2]
                if not MonthlyVipReward.objects.filter(customer=customer,month=month).exists():
                    # A distinct demo voucher per month respects UserVoucher's uniqueness.
                    code=f'CW-HUB-THANKS-{month:%Y%m}'
                    voucher,_=Voucher.objects.get_or_create(code=code,defaults={
                        'name':f'Tri ân mẫu {month:%m/%Y}','description':'Voucher mẫu thống kê CW-HUB',
                        'distribution_type':'ASSIGNED','discount_type':'FIXED','discount_value':50000,
                        'min_order_amount':300000,'start_at':now-timedelta(days=1),'end_at':now+timedelta(days=45),
                    })
                    uv=assign_voucher_to_customer(voucher_id=voucher.pk,customer_id=customer.pk,admin_user=admin,note='Dữ liệu thử thống kê')
                    MonthlyVipReward.objects.create(customer=customer,month=month,user_voucher=uv)
        self.stdout.write(self.style.SUCCESS(f'Created orders={created_orders}, earnings={created_earnings}, favorites={created_favorites}.'))
        self.stdout.write('Test months: '+', '.join(month.strftime('%Y-%m') for month in periods))
        self.stdout.write('Reserved accounts: cw_hub_demo_*. Vouchers: CW-HUB-VIP-50K, CW-HUB-VIP-100K.')
