# CleanWise Backend

Backend API cho nền tảng đặt dịch vụ dọn dẹp **CleanWise** (tương tự bTaskee). Phục vụ 3 ứng dụng: **Customer app**, **Worker app** (React Native / Expo) và **Admin dashboard**. Xây dựng bằng Django 6.1 + DRF, chat realtime qua WebSocket (Channels), tác vụ nền bằng Celery + RabbitMQ, cache bằng Redis, cơ sở dữ liệu PostgreSQL (Neon), thanh toán qua PayOS.

## Công nghệ

| Lớp | Công nghệ |
|---|---|
| Backend | Python 3.13, Django 6.1, Django REST Framework 3.18 |
| Xác thực | JWT (`simplejwt`, refresh + blacklist), Google OAuth, OTP email quên mật khẩu |
| Realtime | Django Channels 4 + Daphne (WebSocket chat) |
| Tác vụ nền | Celery 5 + RabbitMQ (beat chạy tác vụ định kỳ) |
| Cache / Channel layer | Redis 7 |
| Cơ sở dữ liệu | PostgreSQL (Neon), `psycopg2-binary` |
| Lưu ảnh | Cloudinary |
| Thanh toán | PayOS (payment link + webhook) |
| Tài liệu API | drf-spectacular (Swagger / OpenAPI) |
| Hạ tầng | Docker Compose (dev / prod) |
| CI/CD | GitLab CI (đang giữ chỗ) |

## Kiến trúc tổng quan

```
┌──────────────────────────────────────────────────────────┐
│   Customer app  ·  Worker app  ·  Admin dashboard          │
│   (React Native / Expo, 3 repo FE riêng)                   │
└───────────────┬──────────────────────┬───────────────────┘
                │ REST /api/*          │ WebSocket (chat)
     ┌──────────▼──────────────────────▼──────────┐
     │   Django 6.1 + DRF  ·  Daphne (ASGI :8000)  │
     │   JWT auth · phân quyền theo vai trò        │
     │   Channels · Swagger (drf-spectacular)      │
     └───┬────────────┬────────────┬──────────────┘
         │            │            │
  ┌──────▼─────┐ ┌────▼─────┐ ┌────▼──────────┐
  │ PostgreSQL │ │  Redis   │ │   RabbitMQ    │
  │   (Neon)   │ │ cache +  │ │ (Celery       │
  │            │ │ channels │ │  broker)      │
  └────────────┘ └──────────┘ └────┬──────────┘
                                   │
                        ┌──────────▼──────────┐
                        │ Celery worker + beat │
                        └─────────────────────┘

  Dịch vụ ngoài:  Cloudinary (ảnh)  ·  PayOS (thanh toán)  ·  SMTP (OTP email)
```

## Cấu trúc thư mục

```
CleanWiseApp/
├── apps/
│   ├── authentication/   # đăng ký, đăng nhập, OTP, hồ sơ worker
│   ├── addresses/        # địa chỉ khách hàng
│   ├── services/         # danh mục & dịch vụ
│   ├── bookings/         # đặt lịch, lịch làm việc, phân công
│   ├── worker/           # khu vực làm việc, nhận việc, check-in/out
│   ├── payments/         # PayOS, phương thức thanh toán, webhook
│   ├── wallets/          # ví, thu nhập nhân viên
│   ├── vouchers/         # voucher, ví voucher
│   ├── reviews/          # đánh giá nhân viên
│   ├── complaints/       # khiếu nại
│   ├── notifications/    # thông báo, push
│   ├── chat/             # chat realtime (consumers, routing)
│   ├── ai_engine/
│   ├── analytics/
│   └── common/           # cache, retry, idempotency, mã hoá, renderer
├── core/
│   ├── settings/         # base.py · dev.py · prod.py · test.py
│   ├── asgi.py
│   └── celery.py
├── docker-compose.yml        # dev: redis + rabbitmq
├── docker-compose.prod.yml   # prod: web + celery + redis + rabbitmq
├── Dockerfile
├── nginx.conf                # giữ chỗ
├── .gitlab-ci.yml            # giữ chỗ
├── requirements.txt
└── manage.py
```

## Tính năng

### Khách hàng
- Đăng ký, đăng nhập (email + Google), quên mật khẩu bằng OTP
- Quản lý hồ sơ và địa chỉ
- Xem dịch vụ, đặt lịch (một lần / định kỳ)
- Ví voucher, áp dụng voucher khi đặt
- Thanh toán qua PayOS
- Chat với nhân viên, đánh giá sau mỗi buổi, gửi khiếu nại
- Thông báo (chuông + push)

### Nhân viên
- Đăng ký hồ sơ, tải giấy tờ xác minh, chờ admin duyệt
- Đăng ký khu vực làm việc
- Xem lịch, nhận / huỷ việc, check-in / check-out
- Ví và thu nhập, xem đánh giá

### Quản trị viên
- Duyệt hồ sơ nhân viên
- Quản lý người dùng, dịch vụ, voucher
- Quản lý booking và phân công
- Kiểm duyệt đánh giá, xử lý khiếu nại

### API
- **Xác thực:** JWT access (ngắn hạn) + refresh (7 ngày, xoay vòng, blacklist)
- **Giới hạn tốc độ:** `auth` 15 req/phút, `otp` 10 req/phút
- **Realtime:** WebSocket chat qua Channels + Redis channel layer
- **Tác vụ nền (Celery beat):**
  - Hết hạn lịch chưa có người nhận (mỗi 60 giây)
  - Xử lý quên check-out (mỗi 60 giây)
  - Nhắc lịch làm việc (mỗi 5 phút)
- **Ảnh:** upload lên Cloudinary
- **Thanh toán:** PayOS payment link + webhook, có idempotency
- **Tài liệu:** Swagger (drf-spectacular)

## Yêu cầu

- Python 3.13
- Docker + Docker Compose
- Tài khoản PostgreSQL (Neon hoặc Postgres local)

## Chạy nhanh (local)

### 1. Cài môi trường

```bash
python -m venv venv
venv\Scripts\activate.bat
pip install -r requirements.txt
```

### 2. Cấu hình môi trường

```bash
copy .env.example .env
```

| Biến | Mô tả |
|---|---|
| `DJANGO_SETTINGS_MODULE` | `core.settings.dev` / `core.settings.prod` |
| `SECRET_KEY` | Khoá Django |
| `DATABASE_URL` hoặc `DB_*` | Kết nối PostgreSQL (`DATABASE_URL` được ưu tiên) |
| `REDIS_URL` | Cache + channel layer |
| `CELERY_BROKER_URL` | RabbitMQ |
| `CELERY_EAGER` | `1` = task chạy đồng bộ (dev), `0` = chạy qua worker |
| `CLOUDINARY_*` | Upload ảnh |
| `PAYOS_*` | Thanh toán |
| `EMAIL_*` | Gửi OTP quên mật khẩu |
| `GOOGLE_CLIENT_ID` | Đăng nhập Google |
| `FIELD_ENCRYPTION_KEY` | Khoá mã hoá trường nhạy cảm |

> Không commit `.env`. Chỉ commit `.env.example` với giá trị giả.

### 3. Bật Redis + RabbitMQ

```bash
docker compose up -d
```

### 4. Migrate và chạy server

```bash
python manage.py migrate
python manage.py seed_areas
python manage.py createsuperuser
python manage.py runserver 0.0.0.0:8000
```

## Celery

Dev mặc định `CELERY_EAGER=1` nên không cần worker. Muốn chạy thật, đặt `CELERY_EAGER=0` rồi mở 2 terminal:

```bash
celery -A core worker -l info -P solo
celery -A core beat -l info
```

(`-P solo` dành cho Windows.)

## Lệnh thường dùng

```bash
python manage.py check                 # kiểm tra cấu hình
python manage.py makemigrations        # tạo migration
python manage.py migrate               # áp dụng migration
python manage.py test                  # chạy test
python manage.py seed_areas            # seed khu vực làm việc
python manage.py seed_chat_demo        # seed dữ liệu chat mẫu
```

## Docker

### Dev: Redis + RabbitMQ

```bash
docker compose up -d
```

Django vẫn chạy bằng `venv` như bình thường. RabbitMQ UI: http://localhost:15672

### Prod (chưa deploy)

```bash
docker compose -f docker-compose.prod.yml up -d --build
```

Gồm 5 service: `web` (Daphne), `celery-worker`, `celery-beat`, `redis`, `rabbitmq`. Service `web` tự chạy `migrate` khi khởi động.

Cần đặt trong `.env` prod:

```dotenv
DJANGO_SETTINGS_MODULE=core.settings.prod
DEBUG=False
ALLOWED_HOSTS=<domain-api>
CORS_ALLOWED_ORIGINS=<domain-fe>
CSRF_TRUSTED_ORIGINS=<domain-api>
```

## CI/CD

`.gitlab-ci.yml` hiện đang giữ chỗ. Dự kiến pipeline: cài đặt → check + test → build image → push registry → deploy.

## Repo liên quan

- Customer app: TODO
- Worker app: TODO
- Admin dashboard: TODO

## Thành viên

Dự án môn học.

| Tên | MSSV | Vai trò |
|---|---|---|
| Phạm Khả Hào | 22674001 | TODO |

## License

TODO