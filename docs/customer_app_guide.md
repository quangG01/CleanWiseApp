# Hướng dẫn sử dụng ứng dụng khách hàng CleanWise

Chương minh họa nằm trong `apps/chatbot/data/customer_app_guide.json`, tách riêng khỏi các chương đặt đơn, thanh toán và quy trình dịch vụ. Có 11 đề mục ổn định và 29 bước tiếng Việt/Anh; `heading`/`text` vẫn là nguồn văn bản cho chatbot.

Phiên bản 3 dùng 20 hình PNG `guide-v3-*.png` trong `apps/chatbot/data/guide_images/`, vẽ lại theo ảnh chụp Android của phiên bản 2. Giữ các mục và nhãn chức năng, bỏ con trỏ chuột, khung giả lập và công cụ nổi. Dữ liệu trong hình là dữ liệu mẫu; chú thích ghi rõ đây là hình minh họa. Các JPG cũ được giữ cho lịch sử phiên bản 2.

Nguồn vẽ có thể chỉnh sửa: `C:/Users/Aquar/.codex/visualizations/2026/10/24/01a16ea2-bd89-7dd1-b4bc-0b3600f0842e/cleanwise-guide-illustrations.html`. Chạy `node output/customer-guide-plan/render_illustrations.cjs` từ thư mục dự án cha để xuất PNG và tọa độ điều khiển, sau đó chạy `python output/customer-guide-plan/build_content.py` để cập nhật nội dung. Khung đánh dấu trong app được tính theo tọa độ điều khiển, không dùng lại tọa độ ảnh chụp cũ. Không thêm phụ thuộc frontend.

## Xuất bản riêng chương này

```powershell
.\myenv\Scripts\python.exe -X utf8 manage.py import_chatbot_help --path apps/chatbot/data/customer_app_guide.json --publish
.\myenv\Scripts\python.exe -X utf8 manage.py embed_help_chunks
```

Import mặc định cũng đọc chương này cùng các bài trong `help_articles.json`. Import lặp lại không tạo bản sao. Nội dung đã xuất bản không sửa trực tiếp: tăng version cho lần cập nhật tiếp theo và đặt tên ảnh mới nếu thay ảnh đã phát hành.

## Đường dẫn đọc

- `/help/<article-id>`: mục lục chương với tên chương đầy đủ.
- `/help/<article-id>?section=dia-chi&step=2`: mở thẳng bước 2 trong mục Địa chỉ.
- `id` của đề mục không đổi khi sắp xếp lại. Không dùng số thứ tự làm khóa liên kết.
- Bài cũ chưa có `steps` vẫn hiển thị bằng phần đọc văn bản hiện tại.

Ảnh được phục vụ qua `/api/chatbot/help-images/<filename>/`. Endpoint chỉ đọc PNG/JPG đi kèm source, không truy cập media tải lên hoặc đường dẫn tùy ý. Nội dung chương vẫn yêu cầu tài khoản và đúng vai trò như trước.

## Kiểm tra

```powershell
.\myenv\Scripts\python.exe -X utf8 manage.py test apps.chatbot.test_guide apps.chatbot.test_knowledge --settings=core.settings.test
```

Frontend: chạy `npx tsc --noEmit` và `node --test scripts/tests/help-guide.test.cjs scripts/tests/chatbot.test.cjs scripts/tests/language.test.cjs scripts/tests/theme.test.cjs` trong `CleanWiseAppFE`.
