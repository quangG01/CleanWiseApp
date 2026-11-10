# Trang thống kê admin

Trang `/dashboard` chỉ hiển thị KPI, biểu đồ tóm tắt, trạng thái đơn và đường dẫn nhanh. Các trang riêng:

- `/dashboard/revenue`: đơn dịch vụ, chi tiết doanh thu, biểu đồ.
- `/dashboard/services`: cơ cấu dịch vụ, doanh thu theo dịch vụ, bảng chi tiết.
- `/dashboard/workers`: xếp hạng nhân viên, phân trang 5 dòng.
- `/dashboard/favorites`: yêu thích theo tháng, dùng chung tháng đang chọn.
- `/dashboard/vip`: khách VIP và cấp voucher riêng.
- `/dashboard/audit`: buổi thiếu sổ thu nhập, buổi thiếu giờ kết thúc và số liệu cần đối soát.

Tháng nằm trong URL, ví dụ `/dashboard/vip?month=2026-10`, được giữ khi chuyển mục, tải lại hoặc dùng nút Back. Màn hình nhỏ dùng danh sách chọn thay cho thanh tab.

## VIP và voucher

`GET /api/admin/reports/vip-customers/?year=2026&month=10&min_bookings=5&page=1&page_size=5`

Khách phải đang hoạt động, có role CUSTOMER. Đếm đơn **được tạo trong tháng theo giờ Việt Nam**, trạng thái COMPLETED, thanh toán PAID và chưa hoàn tiền. Một gói nhiều buổi vẫn là một đơn. Xếp hạng theo số đơn giảm dần, sau đó tổng giá trị đơn và ID khách.

`POST /api/admin/reports/vip-customers/reward/`

```json
{
  "year": 2026,
  "month": 10,
  "min_bookings": 5,
  "voucher_id": 123,
  "customer_ids": [456, 789]
}
```

Chỉ ADMIN truy cập. Chỉ cấp voucher ASSIGNED đang hoạt động, chưa hết hạn và đủ lượt. Backend kiểm tra lại điều kiện của từng khách; cả đợt nằm trong một transaction. Nếu một người không đủ điều kiện hoặc voucher không đủ lượt, không cấp một phần. Mỗi khách chỉ nhận một đợt tri ân cho mỗi tháng, kể cả chọn mã voucher khác. Gửi lại yêu cầu bỏ qua khách đã được tri ân, không tăng số lượt cấp lần nữa. Bảng `analytics_monthlyvipreward` giữ lịch sử này; voucher được thu hồi sau đó vẫn giữ dấu đã tri ân.

Giới hạn 50 khách mỗi yêu cầu. Giao diện cho chọn khách qua nhiều trang, xem lại danh sách và điều kiện voucher trước khi xác nhận. Không phát sinh email/push trong thao tác cấp voucher này.

## Migration và dữ liệu thử

Tại thư mục backend:

```powershell
.\myenv\Scripts\python.exe manage.py migrate analytics --settings=core.settings.dev
.\myenv\Scripts\python.exe manage.py seed_statistics_hub --settings=core.settings.dev --months=3
```

Có thể thêm `--date=2026-11-02` để giữ ngày neo. Lệnh chỉ chạy khi DEBUG=True, ngày không ở tương lai, tối đa 12 tháng. Chạy lại cùng tháng không tạo trùng. Tài khoản mẫu dùng mật khẩu không đăng nhập được; sử dụng admin hiện có để xem thống kê.

- Tài khoản: `cw_hub_demo_customer_*`, `cw_hub_demo_worker_*`.
- Đơn: `CW-HUB-*`; dịch vụ: `CW_HUB_DEMO_*`.
- Voucher để thử cấp: `CW-HUB-VIP-50K`, `CW-HUB-VIP-100K`.
- Voucher đã cấp mẫu: `CW-HUB-THANKS-YYYYMM`.
- Có khách vượt/chưa đạt ngưỡng VIP, đã/chưa được tri ân; đơn hủy, chưa thanh toán và hoàn tiền; buổi thiếu sổ thu nhập và giờ kết thúc.
- Dữ liệu thu nhập là fixture báo cáo; không cộng/trừ số dư ví hoặc tạo giao dịch thanh toán thực tế.

Đã nạp với ngày neo 02/11/2026, ba tháng 09–11/2026: 196 đơn, 166 dòng thu nhập và 174 bản ghi yêu thích mới. Số liệu toàn trang cộng cả dữ liệu đã có trước đó.

## Kiểm tra

```powershell
.\myenv\Scripts\python.exe manage.py test apps.analytics.tests_vip_report apps.analytics.tests --settings=core.settings.test --noinput
.\myenv\Scripts\python.exe manage.py check --settings=core.settings.dev
```

Tại thư mục dashboard:

```powershell
npx tsc --noEmit
npx eslint src/features/reports src/services/reportApi.ts
npx next build --webpack
```

Trong môi trường Windows hiện tại, Turbopack gặp lỗi khởi tạo tiến trình biên dịch CSS. Webpack build đã qua; nếu cần chạy dev trên máy này: `npm run dev -- --webpack`.

Thử thủ công: chọn tháng 10 hoặc 11/2026, chuyển đủ 7 mục, tải lại URL và dùng Back; tại Khách VIP, đổi ngưỡng, chọn khách qua các trang, chọn voucher 50K/100K, xem lại rồi xác nhận. Khách đã nhận chuyển thành “Đã tặng”, không thể chọn lại. Đối soát mở đúng đơn để kiểm tra.
