# Chatbot M2 hướng dẫn có nguồn

Ngày triển khai: 09/10/2026 theo Asia/Bangkok.

M2 bổ sung `search_help_articles` vào agent M1. Công cụ tìm đoạn nội dung từ các tài liệu đã xuất bản, đang có hiệu lực và dành cho CUSTOMER. Tìm kiếm chuẩn hóa tiếng Việt có dấu/không dấu, mở rộng một số từ đồng nghĩa và xếp hạng độ khớp chủ đề cùng tiêu đề mục. Kho ban đầu nhỏ nên không cần embeddings/pgvector. Mỗi lần hỏi đọc trực tiếp DB, không có chỉ mục ngoài hoặc cache câu trả lời dùng chung giữa khách.

## Nội dung ban đầu

Bốn tài liệu Word được chuyển thành 42 mục trong `apps/chatbot/data/help_articles.json`:

- Quy trình sử dụng dịch vụ.
- Hướng dẫn sử dụng ứng dụng khách hàng.
- Hướng dẫn đặt đơn dịch vụ.
- Hướng dẫn thanh toán và sử dụng Ví CleanWise.

Các tài liệu được dùng theo yêu cầu tích hợp M2 của chủ sản phẩm. Ngày hiệu lực bản nhập là 09/10/2026. Nội dung hướng dẫn không tự xác lập phí hủy, thời hạn hoàn tiền hoặc cam kết chất lượng. Prompt buộc agent tra nguồn trong lượt hiện tại cho hướng dẫn/chính sách, hỏi thêm khi thiếu nguồn và dùng công cụ M1 cho dữ liệu đơn/thanh toán hiện tại. Số dư ví chưa có công cụ tra riêng nên chatbot không tự khẳng định số dư.

## Cài đặt

Trong virtualenv backend, sau khi cập nhật mã:

```powershell
python manage.py migrate chatbot --settings=core.settings.dev
python manage.py import_chatbot_help --publish --settings=core.settings.dev
```

Dùng settings của môi trường triển khai thực tế khi chạy trên server. Lệnh không có `--publish` tạo bản nháp. Nhập lại cùng slug/version/nội dung không tạo trùng; nếu nội dung thay đổi phải tăng version. Không tự ghi đè bản đã xuất bản. Các biến môi trường Gemini/checkpoint vẫn dùng cấu hình M1. Khởi động lại backend đang chạy và tải lại app để nhận mã M2.

## Quản lý nội dung

Django admin có HelpArticle với slug, version, title, summary, sections, keywords, role, source_document, trạng thái và thời gian hiệu lực. `sections` là danh sách đối tượng `{heading, text}` với văn bản thuần. Mỗi tài liệu có bản nháp, bản xuất bản hoặc bản thu hồi.

Bản đã từng xuất bản không sửa nội dung; tạo bản nháp có cùng slug, version lớn hơn để cập nhật. Xuất bản phiên bản mới thu hồi phiên bản cũ trong transaction. Ràng buộc DB đảm bảo một bản xuất bản cho mỗi slug. Bản thu hồi không xuất bản lại và không tự hồi sinh bản cũ khi bản mới bị thu hồi. Nếu bản mới có ngày hiệu lực ở tương lai, bản cũ được thu hồi ngay lúc xuất bản; chỉ xuất bản vào thời điểm muốn chuyển bản hoặc giữ bản mới ở nháp đến ngày hiệu lực.

Nguồn cũ trong lịch sử chat mở sẽ trả 404 khi đã thu hồi. Văn bản câu trả lời đã lưu vẫn là lịch sử; để xem dữ liệu hiện tại cần hỏi lại. Có thể thêm nội dung FAQ/chính sách mới trong admin mà không đổi code.

## API và giao diện

- `GET /api/chatbot/help-articles/`: danh sách tài liệu hiện hành dành cho khách; dùng JWT CUSTOMER.
- `GET /api/chatbot/help-articles/{id}/`: nội dung và phiên bản. Nháp, thu hồi, khác vai trò, chưa hiệu lực hoặc hết hiệu lực trả 404.
- Card `help` có `article_id`, `version`, `effective_from`, `title`, `label` và `action=OPEN_HELP_ARTICLE`.

Backend đính kèm nguồn thực sự đã được truy xuất trong lượt, kể cả khi model quên chọn thẻ. ID do model tự tạo không có trong artifacts không được chấp nhận. Nguồn được kiểm tra lại trạng thái trước khi tạo thẻ, tổng thẻ tối đa 5.

App có kho hướng dẫn `/help`, màn hình `/help/[id]`, thẻ nguồn trong câu trả lời và câu hỏi gợi ý đặt dịch vụ/nạp ví. Mở kho qua biểu tượng sách trên Trợ lý hoặc Cá nhân → Hướng dẫn sử dụng. Màn hình nguồn tải lại API khi mở, không dùng nội dung do model truyền qua route. Nếu nguồn bị thu hồi, không hiển thị nội dung cache cũ.

## Kiểm chứng

```powershell
python manage.py check --settings=core.settings.test
python manage.py test apps.chatbot --settings=core.settings.test --noinput
```

FE chạy `npm run test:chatbot` và `npx tsc --noEmit`. Kiểm thử M2 gồm tìm kiếm có/không dấu, nguồn cho chủ đề đặt đơn/thanh toán, kết quả rỗng cho câu ngoài phạm vi, phân quyền, ngày hiệu lực, bản nháp/thu hồi, nội dung bất biến, phiên bản mới thay thế bản cũ, tool loop LangChain và thẻ nguồn tự đính kèm. FE kiểm tra mở đúng nguồn và không hiển thị nội dung cũ khi API trả 404.

Kết quả: 39/39 kiểm thử backend, 25/25 kiểm thử FE và TypeScript đạt; model không thiếu migration. Migration M2 và bốn tài liệu đã được áp dụng vào database phát triển. Đã kiểm chứng Gemini thật với câu hỏi nạp ví: agent gọi tìm nguồn, trả các bước đúng nội dung và đính kèm nguồn phiên bản 1. Checkpoint kiểm chứng đã xóa sau chạy. Chưa kiểm chứng trực quan trên thiết bị hoặc app đang chạy trong lượt này.
