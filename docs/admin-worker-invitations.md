# Lời mời nhận việc từ admin

Admin gửi lời mời có thời hạn cho từng buổi. BookingAssignment ở trạng thái
PENDING trong thời gian chờ; chỉ chuyển sang ACCEPTED khi nhân viên đồng ý.
Ví, trạng thái booking, thông báo khách hàng và chat chỉ kích hoạt khi nhận việc.

## Bản xem thử trên máy

- API: http://127.0.0.1:8010
- Dashboard: http://127.0.0.1:3010
- App nhân viên (web): http://127.0.0.1:8082
- Admin: `preview-admin`
- Nhân viên: số điện thoại `0900000003`
- Mật khẩu cả hai: `Invitation@Test123`

Tài khoản và dữ liệu trên chỉ nằm trong SQLite riêng:
`CleanWiseApp/.local/invitation-preview.sqlite3`. Seed bị chặn khi chạy bằng
settings khác. Không dùng settings này để triển khai server.

Đơn mẫu gồm CW-INVITE-OPEN, CW-INVITE-WAITING và CW-INVITE-EXPIRED.
Trong dashboard chọn tab **Chờ xử lý** để tìm đơn chưa có người nhận.
Lời mời có hạn thực tế, nên mẫu WAITING sẽ tự hết hạn sau 60 phút.

Mở lại API trong terminal ở CleanWiseApp:

```powershell
New-Item -ItemType Directory -Path .local -Force
./myenv/Scripts/python.exe manage.py migrate --run-syncdb --settings=core.settings.invitation_preview --noinput
./myenv/Scripts/python.exe manage.py seed_invitation_preview --settings=core.settings.invitation_preview
./myenv/Scripts/python.exe manage.py runserver 127.0.0.1:8010 --noreload --settings=core.settings.invitation_preview
```

Mở dashboard trong terminal ở CleanWiseDashboard:

```powershell
$env:CLEANWISE_PREVIEW='1'
$env:NEXT_PUBLIC_API_URL='http://127.0.0.1:8010'
node node_modules/next/dist/bin/next build
node node_modules/next/dist/bin/next start --port 3010 --hostname 127.0.0.1
```

Mở app nhân viên trong terminal ở CleanWiseStaffFE:

```powershell
$env:EXPO_PUBLIC_API_URL='http://127.0.0.1:8010'
node node_modules/expo/bin/cli start --web --port 8082
```

App web hỗ trợ kiểm tra giao diện và thông báo trong ứng dụng. Push hệ điều hành
cần kiểm tra trên thiết bị Android/iOS với token thật. Khi dùng Android emulator,
địa chỉ API là `http://10.0.2.2:8010`; cấu hình địa chỉ bind API phù hợp trước khi chạy.

## Quy tắc

- Một lời mời PENDING cho mỗi buổi, được bảo vệ bởi unique constraint và khóa booking.
- Thời hạn: 15, 30 hoặc 60 phút; kết thúc ít nhất 30 phút trước giờ làm.
- Nhân viên phải phù hợp dịch vụ, khu vực, lịch và điều kiện ví tiền mặt.
- Kiểm tra lại điều kiện lúc nhận; thất bại sẽ giữ nguyên lời mời PENDING.
- Lời mời đang hiệu lực giữ quyền nhận cho người được mời ở đúng buổi đó.
- Từ chối, thu hồi hoặc hết hạn mở buổi lại cho danh sách chung.
- Lời mời ưu tiên của khách hàng phải được thu hồi trước khi admin gửi lời mời mới.
- Buổi đã có người nhận cần bỏ phân công trước khi mời người khác.
- Đổi lịch thu hồi lời mời đang chờ. Hủy đơn/buổi đóng lời mời theo luồng hủy hiện có.
- Gửi nhiều buổi trả kết quả riêng cho từng buổi; kiểm tra điều kiện cho từng buổi.
- Notification lưu navigation_source để thông báo trong app mở đúng màn.
- Push và badge lời mời được phát sau khi giao dịch cơ sở dữ liệu commit.

## API

Các URL assign cũ được giữ tương thích, nhưng bây giờ tạo lời mời PENDING:

- POST `/api/admin/schedules/{id}/assign/`: worker_id, response_minutes.
- POST `/api/admin/schedules/bulk-assign/`: booking_id, schedule_ids, worker_ids (hoặc worker_id cho client cũ), response_minutes.
- POST `/api/admin/schedules/{id}/invitation/withdraw/`: reason.
- POST `/api/worker/invitations/{id}/respond/`: action = accept hoặc decline.
- GET `/api/admin/bookings/?invitation_state=waiting`: các đơn có lời mời đang chờ.

Serializer admin trả invitation, assignment_history và waiting_invitations.
Serializer nhân viên chỉ trả lời mời thuộc chính tài khoản đang gọi API.

## Đưa lên server sau khi kiểm tra local

1. Cập nhật backend và chạy migration với settings/database triển khai bình thường.
2. Migration worker 0006 đóng các bản ghi PENDING cũ và thêm ràng buộc một lời mời chờ mỗi buổi.
   Migration worker 0007 xóa cột invitation_note; lời mời dùng nội dung mặc định, không có ô nhập lời nhắn. Migration notifications 0006 thêm nguồn điều hướng.
3. Khởi động lại API và Celery worker/beat. Task expire_unclaimed_schedules hiện có
   sẽ xử lý lời mời hết hạn; không cần thêm lịch beat.
4. Build/phát hành dashboard và app nhân viên cùng phiên bản backend.

## Kiểm tra

```powershell
./myenv/Scripts/python.exe manage.py test apps.bookings.test_admin_api apps.worker.tests apps.bookings.test_admin_worker_schedule --settings=core.settings.test --noinput
```

Đã kiểm tra TypeScript hai frontend, build Next.js, export bundle Android và thao tác
gửi/nhận lời mời trực tiếp qua hai giao diện local.

Kiểm thử booking rộng hơn có 3 lỗi assertion thanh toán/voucher và 1 lỗi fixture
ví thiếu số dư; các lỗi này cũng tái hiện khi dùng assignment_service gốc từ HEAD.
SQLite smoke của lịch sử migration bỏ qua câu DROP COLUMN IF EXISTS chỉ dành cho
PostgreSQL ở migration bookings 0003 cũ. Chưa kiểm tra migration trên PostgreSQL.

## Mời nhiều nhân viên

Nút ngoài là Phân công. Popup hiển thị sẵn thẻ nhân viên, có tìm kiếm và phân trang
4 thẻ mỗi trang. Bấm thẻ để xem hồ sơ, tích checkbox để chọn hoặc chọn từ hồ sơ;
giữ lựa chọn khi đổi trang. Tối đa 100 người mỗi lần gửi. Nút xác nhận là Gửi lời mời nhận việc.
Mỗi buổi kiểm tra lại toàn bộ nhân viên đã chọn; nếu một người không còn đủ điều kiện,
buổi đó bị bỏ qua và trả lý do, không gửi một phần khó theo dõi.
Migration worker 0008 cho phép nhiều lời mời PENDING trên một buổi, nhưng mỗi nhân viên
chỉ có một lời mời PENDING; ràng buộc một ACCEPTED mỗi buổi vẫn được giữ.
Người xác nhận đầu tiên nhận việc, các lời mời còn lại tự đóng và có thông báo.
Từ chối một lời mời không mở buổi làm khi vẫn còn người khác đang chờ.
Thu hồi tại admin đóng toàn bộ lời mời đang chờ của buổi.

## Dữ liệu test trên PostgreSQL development

```powershell
./myenv/Scripts/python.exe manage.py seed_invitation_card_tests --area-id 7
```

Command chỉ chạy với DEBUG và settings dev/preview. Dùng dịch vụ HOME_CLEANING_HOURLY,
tạo lịch tương lai và thanh toán CASH qua create_booking; kiểm tra nhân viên phù hợp
trước khi commit. Không gửi lời mời tự động. Chạy lại cùng --batch không tạo trùng,
không đặt lại mật khẩu, không sửa trạng thái đơn đã test. --batch có thể đổi để tạo
một nhóm đơn mới khi nhóm cũ đã quá ngày hoặc đã nhận việc.

- Khách: card_test_customer, số điện thoại 0999000100.
- Nhân viên test: card_test_worker_01 / 0999000201 và card_test_worker_02 / 0999000202.
- Mật khẩu ban đầu của tài khoản test mới: Cards@Test123.
- Hai nhân viên test ACTIVE, có ví test 2.000.000 và là nhân viên khách test yêu thích.
- Nhóm CW-CARDS-20261010-01 đến CW-CARDS-20261010-05, booking id 187–191,
  có 8–10 ứng viên phù hợp lúc seed. Dashboard dev tại http://127.0.0.1:3000.

Dữ liệu này thuộc PostgreSQL dev, khác database SQLite của bản xem thử 3010/8010.

App nhân viên web đang chạy tại http://127.0.0.1:8082 đã được chuyển sang API dev
http://127.0.0.1:8000 để đăng nhập các tài khoản card_test và nhận đơn 187–191.
Dashboard dev 3000 dùng dữ liệu PostgreSQL này; dashboard xem thử 3010 vẫn dùng SQLite.

## Dữ liệu test ba tab nhân viên

```powershell
./myenv/Scripts/python.exe manage.py seed_worker_tab_tests --area-id 7 --settings=core.settings.dev
```

Command tạo một khách riêng `tabs_test_customer` (0999000300), bảy nhân viên
`tabs_test_worker_01` đến `_07` (0999000301–0999000307), mật khẩu ban đầu
`Tabs@Test123`. Sáu người đầu thuộc danh sách yêu thích; người thứ bảy chỉ
thuộc nhóm phù hợp. Không thay đổi tài khoản/đơn của bộ test trước.

Sáu đơn `CW-TABS-20261010-01` đến `-06` lần lượt minh họa khách yêu cầu
nhân viên phù hợp, trùng lịch, thiếu số dư, ngoài khu vực, khác dịch vụ,
hồ sơ chưa được duyệt. Lựa chọn của khách được lưu trên buổi làm, với thời
hạn ưu tiên đã hết để admin mở popup. Đây là lịch sử lựa chọn mô phỏng,
không phải lời mời đang chờ phản hồi.

Đơn `CW-TABS-20261010-BUSY` là ca đã nhận của nhân viên 02, chỉ để tạo lịch
trùng cho đơn `-02`. Không dùng đơn này để kiểm tra gửi lời mời. Các đơn
mới tạo qua luồng đặt đơn CASH; profile fixture không phát thông báo xét
duyệt, assignment fixture không phát thông báo phân công. Chạy lại cùng
batch giữ mật khẩu, ví và trạng thái đã test; đổi `--batch` để thêm bộ mới.

Đã seed trên Neon ngày 10/10/2026: các đơn chính có ID 199, 200, 202,
203, 204, 205; đơn phụ trùng lịch có ID 201. Lịch các đơn chính lần lượt
12–17/10/2026 lúc 08:00–10:00. Tìm `tabs_test` trong popup để lọc riêng
các nhân viên thuộc bộ dữ liệu này.

## Tải danh sách popup một lần

FE gọi `GET /api/admin/schedules/<id>/available-workers/?group=all` khi
mở popup. Chế độ này trả toàn bộ hợp của nhân viên phù hợp, nhân viên
khách yêu thích và nhân viên khách yêu cầu, mỗi người một bản ghi; giữ
lý do không nhận ca cho các nhân viên liên quan đến khách. Các chế độ
group cũ vẫn phân trang như trước.

Chuyển tab, tìm kiếm theo tên/tài khoản/số điện thoại và phân trang 12
thẻ xử lý tại FE, không gửi thêm request danh sách. Đóng rồi mở lại sẽ
refetch. Backend vẫn kiểm tra lại điều kiện khi gửi và nhận lời mời.
