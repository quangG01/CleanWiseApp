# Lịch tuần nhân viên trên admin

Mở **Nhân viên → tên nhân viên / Xem chi tiết → Lịch làm việc**.
UI dùng các thành phần shadcn hiện có: Tabs, Dialog, Button, Badge, Card và Skeleton.
Lịch gồm 7 ngày, trục giờ 00:00–24:00; nền xanh nhạt là khung giờ đăng ký hiện tại.
Các buổi trùng giờ chia cột; buổi qua nửa đêm được chia thành từng ngày.
Ô công việc chỉ hiển thị giờ làm và trạng thái. Dịch vụ và mã đơn chỉ xuất hiện trong chi tiết.
Chọn ô để mở màn hình chi tiết trong cùng cửa sổ: thông tin, giờ thực tế, ghi chú, liên kết ảnh và mở đơn hàng.
Nút Quay lại lịch giữ nguyên tuần và vị trí cuộn; chi tiết không đẩy lịch xuống hoặc tạo thanh cuộn bên ngoài tab.

## API

`GET /api/admin/workers/{worker_user_id}/schedule/?start=2026-09-28&end=2026-10-05`

- Chỉ ADMIN hoặc superuser; ID là tài khoản nhân viên, không phải ID WorkerProfile.
- Khoảng ngày theo Asia/Ho_Chi_Minh, ngày kết thúc không bao gồm trong lịch, tối đa 31 ngày.
- Bỏ tham số để lấy tuần hiện tại (thứ Hai đến Chủ nhật).
- `availability`: weekday 0 = thứ Hai, 6 = Chủ nhật; chỉ khung giờ is_active.
- `assignments`: buổi giao với khoảng ngày, ưu tiên phân công ACCEPTED, sau đó PENDING mới nhất.
- REJECTED, CANCELLED, EXPIRED của phân công không được đưa vào lịch; trạng thái buổi làm được trả riêng.
- Khung giờ đăng ký chưa có lịch sử thay đổi hoặc ngày nghỉ ngoại lệ.
- FE tải khi mở tab/đổi tuần và làm mới cache sau mutation đơn hàng.

## Dữ liệu test

Chạy từ thư mục CleanWiseApp bằng môi trường Python hiện có:

```powershell
.\myenv\Scripts\python.exe -X utf8 manage.py seed_worker_schedule_demo --settings=core.settings.dev
```

Có thể truyền `--week 2026-10-01` hoặc `--worker-id 3`.
Lệnh tạo hai tuần cho tối đa ba nhân viên ACTIVE có dịch vụ; dùng khách hàng và admin đang có.
Chỉ thêm khung giờ đăng ký nếu nhân viên chưa có khung giờ active.
Mã đơn bắt đầu bằng `CW-WK-`; chạy lại cùng tuần không tạo trùng hoặc sửa đơn cũ.
Gồm buổi đã nhận, đã hoàn thành theo thời gian, chờ xác nhận trùng giờ và buổi qua nửa đêm.
Đơn mẫu được ghi nhận thanh toán chuyển khoản, không gọi cổng thanh toán hoặc gửi thông báo.

Đã tạo 36 đơn vào 01/10/2026, tuần 28/09 và 05/10, cho tài khoản:

| worker_user_id | username | tên |
| --- | --- | --- |
| 3 | demo.review.worker | Nguyễn Minh An |
| 6 | chat_demo_worker | Nhân viên Demo Chat |
| 28 | admin_test_worker_02 | Quốc Bảo Trần |

## Kiểm tra

Backend:

```powershell
.\myenv\Scripts\python.exe -X utf8 manage.py test apps.bookings.test_admin_api apps.bookings.test_admin_worker_schedule --settings=core.settings.test --noinput
```

Frontend (từ CleanWiseDashboard):

```powershell
npx tsc --noEmit
node tests/workerScheduleLayout.test.mjs
```
