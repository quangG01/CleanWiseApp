# Chatbot khách hàng M1 — Backend

M2 đã được bổ sung ngày 09/10/2026: xem [kho hướng dẫn, API nguồn và cách xuất bản](chatbot-m2.md). Các giới hạn RAG bên dưới mô tả phạm vi M1 ban đầu; M2 hiện hỗ trợ hướng dẫn từ tài liệu đã xuất bản.

Triển khai ngày 08/10/2026: Django/DRF + LangChain `create_agent` (vòng agent do LangGraph thực thi), Google Gemini Developer API và PostgreSQL. FE sẽ tích hợp ở bước sau.

## Phạm vi và câu hỏi hỗ trợ

| Chức năng | Ví dụ | Tool |
| --- | --- | --- |
| Tìm, gợi ý dịch vụ từ danh mục hoạt động | “Có dịch vụ dọn căn hộ không?”, “Vệ sinh máy lạnh gồm những lựa chọn nào?” | `search_services`, `get_service_details` |
| Thông tin dịch vụ và bảng giá cấu hình | “Dọn nhà có những gói nào?” | `get_service_details` |
| Tra các đơn của tài khoản hiện tại | “Đơn gần nhất của tôi?”, “Các đơn đang làm?”, “Ngày mai tôi có đơn nào?” | `list_my_bookings` |
| Tiến độ, phân công, check-in, thanh toán | “Đơn CW-… có nhân viên chưa?”, “Đã check-in chưa?”, “Đơn đã thanh toán chưa?” | `get_my_booking_detail` |
| Lịch theo buổi và số buổi còn lại | “Đơn này còn mấy buổi?”, “Buổi tiếp theo lúc nào?”, “Xem các buổi còn lại” | `get_my_booking_detail`, `get_my_booking_schedules` |
| Mở màn hình tương ứng | Thẻ dịch vụ, đơn, buổi dịch vụ từ kết quả tra cứu | Backend tạo `cards` từ tool artifacts |

Chỉ triển khai công cụ đọc. Hỗ trợ báo cáo/khiếu nại đã loại khỏi M1 theo yêu cầu. RAG/FAQ/chính sách, đặt lịch qua chatbot và graph nghiệp vụ tùy biến dành cho các mốc sau. Model không được tự suy diễn chính sách hoặc tính báo giá cuối cùng từ bảng giá.

## Cấu hình và khởi chạy

Trong virtualenv backend:

```powershell
python -m pip install -r requirements.txt
python manage.py migrate chatbot --settings=core.settings.dev
python manage.py setup_chatbot_checkpoints --settings=core.settings.dev
```

Điền cấu hình vào `.env` trên server rồi khởi động lại backend:

```dotenv
GOOGLE_API_KEY=your-key
CHATBOT_ENABLED=1
CHATBOT_MODEL=gemini-3.5-flash-lite
```

Cũng chấp nhận `GEMINI_API_KEY` nếu `GOOGLE_API_KEY` chưa có. Các giới hạn còn lại nằm trong `.env.example`: 20 giây/model call, ngân sách lượt 90 giây, tối đa 6 model call và 8 tool call, 2048 output token, 6 cặp hội thoại gần nhất/16000 ký tự, 10 mutation/phút/user. Ngân sách thời gian được kiểm tra trước model/tool; request đang chạy có thể vượt ngân sách đến khi call hiện tại kết thúc. FE nên có timeout ít nhất 120 giây và giữ UUID để phục hồi khi mất kết nối.

Checkpoint dùng cùng credentials/database với Django nhưng kết nối psycopg riêng, schema `chatbot_checkpoints`. Với Neon, host `-pooler` tự chuyển sang direct endpoint vì checkpoint cần session `search_path`. Với pool khác, đặt `CHATBOT_CHECKPOINT_DB_HOST` bằng host PostgreSQL trực tiếp. DB user cần quyền tạo schema/bảng khi chạy setup; request thường không chạy DDL. Lệnh setup có thể chạy lại.

Lỗi model tạm thời (`500/502/503/504` hoặc timeout) được `ModelRetryMiddleware` thử lại tối đa một lần với backoff khoảng 1 giây. Chỉ gọi lại model, không gửi lại toàn bộ lượt hoặc chạy lại tool đã hoàn tất. Timeout mỗi lần gọi bị giới hạn bởi ngân sách lượt còn lại. Lỗi key/model hoặc quota không tự retry. Khi vẫn lỗi, API trả `503` với mã `CHATBOT_PROVIDER_BUSY`, `CHATBOT_MODEL_TIMEOUT`, `CHATBOT_RATE_LIMITED` hoặc `CHATBOT_PROVIDER_CONFIG_ERROR`; FE hiển thị thông báo tương ứng. Không tự đổi model hoặc trả câu trả lời giả.

## API

Yêu cầu JWT của user đang hoạt động, role `CUSTOMER`. Tài khoản khác không được truy cập hội thoại/đơn của chủ sở hữu. ID người dùng luôn lấy từ JWT, không lấy từ payload hoặc arguments model.

| Method | Path | Ý nghĩa |
| --- | --- | --- |
| GET / POST | `/api/chatbot/conversations/` | Liệt kê / tạo hội thoại |
| GET / PATCH / DELETE | `/api/chatbot/conversations/{id}/` | Xem / sửa `title`, `status` / xóa hội thoại |
| GET / POST | `/api/chatbot/conversations/{id}/messages/` | Lịch sử / gửi câu hỏi và nhận câu trả lời đồng bộ |
| GET | `/api/chatbot/runs/{uuid}/` | Xem lượt xử lý, tin người dùng và câu trả lời nếu có |

Danh sách hội thoại mới cập nhật trước; tin nhắn cũ trước. Phân trang `?page=1&page_size=20`, tối đa 50. Response GET list có `count`, `next`, `previous`, `results` bên trong `data`.

Tạo hội thoại: body `{}` hoặc `{"title":"Tra đơn của tôi"}`. Backend tự đặt title từ câu hỏi đầu nếu để trống. PATCH status không được thực hiện khi có run `RUNNING`.

DELETE trả `204` và xóa vĩnh viễn hội thoại, toàn bộ tin nhắn, runs và checkpoints của mọi lần thử trong cùng transaction. Chỉ chủ hội thoại được xóa; ID không tồn tại hoặc thuộc tài khoản khác trả `404`. Nếu có run `RUNNING`, trả `409 CONVERSATION_BUSY` và giữ nguyên dữ liệu.

Gửi tin nhắn:

```http
POST /api/chatbot/conversations/12/messages/
Authorization: Bearer <access-token>
Content-Type: application/json

{
  "text": "Đơn gần nhất của tôi có nhân viên chưa?",
  "client_message_id": "c4b6ad40-d18f-4a85-a4d2-5d680b8b03b4"
}
```

`text`: không rỗng, tối đa 2000 ký tự sau trim. FE tạo một UUID cho mỗi tin mới, giữ nguyên text/UUID khi retry.

Response thành công theo renderer chung, HTTP 201 cho câu trả lời mới hoặc 200 cho replay. Ví dụ rút gọn các trường thời gian:

```json
{
  "success": true,
  "status_code": 201,
  "message": "Call API thành công",
  "data": {
    "conversation_id": 12,
    "run": {
      "id": "018c76e0-65b7-4a2b-97f9-72e2e825d5b6",
      "status": "SUCCEEDED",
      "error_code": "",
      "attempts": 1,
      "duration_ms": 1800
    },
    "user_message": {
      "id": 24,
      "role": "user",
      "text": "Đơn gần nhất của tôi có nhân viên chưa?",
      "cards": [],
      "status": "COMPLETED",
      "client_message_id": "c4b6ad40-d18f-4a85-a4d2-5d680b8b03b4",
      "run_id": "018c76e0-65b7-4a2b-97f9-72e2e825d5b6"
    },
    "assistant_message": {
      "id": 25,
      "role": "assistant",
      "text": "Đơn CW-… đã có nhân viên nhận. Chưa có dữ liệu check-in.",
      "cards": [{
        "type": "booking",
        "booking_id": 98,
        "title": "CW-…",
        "action": "OPEN_BOOKING",
        "label": "Xem đơn"
      }],
      "status": "COMPLETED",
      "client_message_id": null,
      "run_id": "018c76e0-65b7-4a2b-97f9-72e2e825d5b6"
    },
    "replayed": false
  }
}
```

Backend còn trả `created_at`, các timestamp của run và envelope `timestamp`. Booking card có `data` là tóm tắt trạng thái đơn/thanh toán/số tiền. Không dựa vào văn bản model để dựng nút hoặc route.

| Card action | Fields | FE xử lý |
| --- | --- | --- |
| `OPEN_SERVICE` | `service_id`, `title`, `label` | Mở chi tiết/chọn dịch vụ theo ID |
| `OPEN_BOOKING` | `booking_id`, `title`, `label`, `data` | Mở chi tiết đơn |
| `OPEN_SCHEDULE` | `schedule_id`, `booking_id`, `title`, `label`, `scheduled_start`, `status`, `status_label` | Mở buổi dịch vụ trong đơn |

Tối đa 5 thẻ/câu trả lời. Agent gọi `select_response_cards` để chọn thẻ phù hợp câu hỏi từ các kết quả đã tra trong lượt hiện tại; backend không tự gộp mọi đơn từng đọc để tìm kiếm. Backend kiểm tra lại dịch vụ hoạt động hoặc quyền sở hữu đơn/buổi trước khi trả thẻ và giữ thứ tự agent chọn. Nếu agent bỏ qua lựa chọn, backend chỉ dùng đơn được nêu mã trong câu trả lời, kết quả chi tiết hoặc một ứng viên duy nhất; không tự gửi toàn bộ danh sách tìm kiếm. Khi không đủ dữ liệu hoặc chọn danh sách rỗng, `cards` có thể rỗng.

`list_my_bookings` hỗ trợ `status`, `payment_status` (UNPAID/PAID/REFUNDED), `service_query` (tên/mã dịch vụ, không phân biệt dấu), ngày lịch dịch vụ và `limit` (1–5 đơn mỗi trang). Bộ lọc được áp dụng trước khi sắp xếp và phân trang; hỏi đơn gần nhất dùng `limit=1`. Giữ nguyên bộ lọc và limit khi chuyển trang.

## Retry, lỗi và lưu dữ liệu

- Một hội thoại chỉ có một run hoạt động. Gửi song song trả 409 `CONVERSATION_BUSY`.
- Cùng UUID và text đã thành công: trả đúng câu trả lời đã lưu, không gọi model lại. UUID đã dùng với text khác: 422 `MESSAGE_ID_REUSED`.
- Run thất bại: có thể gửi lại cùng UUID/text để thử lại, không nhân đôi tin người dùng. Nếu đã gửi tin mới hơn, retry tin cũ trả 409 `OUTDATED_RETRY`; gửi lại câu hỏi bằng UUID mới.
- Sau lỗi mạng, tải lịch sử, tìm `client_message_id` để lấy `run_id`, rồi GET run nếu cần. `RUNNING`, `SUCCEEDED`, `FAILED` là trạng thái run; `PROCESSING`, `COMPLETED`, `FAILED` là trạng thái message.
- Lease của run bằng ngân sách lượt + model timeout + 60 giây. Request mới thu hồi run quá hạn; worker cũ không được ghi câu trả lời vào lượt đã thay thế.
- Không có Gemini key hoặc chatbot bị tắt: 503 `CHATBOT_NOT_CONFIGURED`; provider/checkpoint/tool lỗi ngoài dự kiến: 503 `CHATBOT_REPLY_FAILED`. Không trả câu trả lời giả.
- Lỗi theo envelope chung: xem `errors.chatbot_error_code` để xử lý các mã chuyên biệt trên; `errors.detail` chứa giải thích. 401/403/404/429 tuân theo API hiện tại.

Transcript lưu trong các bảng sẵn có `chatbot_sessions`, `chatbot_messages` (app `ai_engine`), mở rộng bằng title/status/cards/client UUID. `chatbot_runs` lưu trạng thái, model, attempt, thời gian và token usage. LangGraph checkpoints ở schema riêng.

Mỗi **attempt** có checkpoint thread riêng để tách worker quá hạn. Hội thoại giữa các lượt được dựng lại từ các cặp user/assistant đã commit thành công, giới hạn theo cấu hình. Đây là lưu checkpoint bền vững cho vòng agent; API hiện tại retry lượt thất bại từ đầu và chưa cung cấp resume giữa chừng. Checkpoint có thể chứa nội dung tool/model nên cần cùng mức kiểm soát truy cập/retention với transcript; hiện chưa có job dọn dữ liệu tự động.

Tool chỉ dùng ORM có phân quyền, không đăng ký SQL toolkit hoặc truy vấn SQL do model sinh. Phân công không đồng nghĩa check-in: chỉ xác nhận check-in khi có `actual_start`. `remaining_sessions` đếm `PENDING`/`IN_PROGRESS`. Ngày lọc đơn dựa vào lịch dịch vụ theo timezone backend; tiền giữ dạng chuỗi Decimal, không trả dữ liệu tài khoản thanh toán hoặc liên hệ riêng của nhân viên.

## Kiểm chứng

```powershell
python manage.py check --settings=core.settings.test
python manage.py test apps.chatbot --settings=core.settings.test --noinput
python manage.py makemigrations --check --dry-run --settings=core.settings.test
```

Đã kiểm thử API/phân quyền, chống trùng tin, retry, worker quá hạn, context từ transcript đã commit, tool loop thật của LangChain với model giả lập, giới hạn gọi model, dữ liệu check-in/thanh toán/lịch và cấu hình kết nối Neon. Đã chạy vòng agent tra danh mục thực tế và xác nhận checkpoint PostgreSQL đọc lại được qua kết nối mới, sau đó xóa namespace kiểm chứng.

Đã kiểm chứng Gemini thật chấp nhận cả 5 schema tool và trả lời câu chào với `tool_choice='none'` (không thực thi tool hoặc gửi dữ liệu DB). Đã sửa lỗi Gemini `INVALID_ARGUMENT` do enum trạng thái chứa chuỗi rỗng: `status` hiện có thể bỏ qua/null, enum chỉ chứa trạng thái đơn hợp lệ. Bộ test chatbot hiện có 19 test đạt.

Bộ 59 test cũ của booking/service/chat còn 6 failure và 8 error; các lỗi này cũng có trên snapshot HEAD trước triển khai chatbot (snapshot còn một error bổ sung do thiếu fixture dịch vụ chưa được track). Cần xử lý riêng các lỗi nghiệp vụ hiện hữu.

Tài liệu framework: [LangChain agents](https://docs.langchain.com/oss/python/langchain/agents), [tools và runtime context](https://docs.langchain.com/oss/python/langchain/tools), [Gemini integration](https://docs.langchain.com/oss/python/integrations/chat/google_generative_ai), [Neon pooled connections](https://neon.com/docs/connect/connection-pooling).
