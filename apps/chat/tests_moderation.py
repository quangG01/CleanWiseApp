from django.test import SimpleTestCase, override_settings

from .moderation import cosine_chunks, detect_violation, normalize_text, reference_index
from .moderation_samples import ALLOWED_SAMPLES, VIOLATION_SAMPLES


class ChatModerationTests(SimpleTestCase):
    def test_split_facebook_spelling_is_blocked_without_blocking_warnings(self):
        for text in (
            'Nhan tin lien he qua face book em nhe',
            'Nhan tin qua Facebook rieng cua em nhe',
            'Nhắn tin liên hệ qua FACE   BOOK em nhé',
            'Liên hệ qua face.book em nhé',
            'Nhắn tin qua face-book riêng của em nhé',
            'Nhắn tin qua face\u200b book em nhé',
        ):
            with self.subTest(text=text):
                violation = detect_violation(text)
                self.assertIsNotNone(violation)
                self.assertEqual(violation.category, 'EXTERNAL_CONTACT')
                self.assertEqual(violation.method, 'regex')
        for text in (
            'Dung nhan tin lien he qua face book, hay dung CleanWise',
            'Không liên hệ qua face-book riêng của em nhé',
            'Ứng dụng có hỗ trợ đăng nhập bằng face book không?',
        ):
            with self.subTest(text=text):
                self.assertIsNone(detect_violation(text))

    def test_seed_examples_are_consistent(self):
        self.assertGreaterEqual(len(VIOLATION_SAMPLES), 50)
        self.assertGreaterEqual(len(ALLOWED_SAMPLES), 50)
        for category, text in VIOLATION_SAMPLES:
            with self.subTest(text=text):
                violation = detect_violation(text)
                self.assertIsNotNone(violation)
                self.assertEqual(violation.category, category)
        for text in ALLOWED_SAMPLES:
            with self.subTest(text=text):
                self.assertIsNone(detect_violation(text))

    def test_contact_formats_and_obfuscation(self):
        cases = (
            ('Số em 0912 345 678 nhé', 'PHONE_NUMBER'),
            ('Liên hệ +84 912 345 678', 'PHONE_NUMBER'),
            ('Gọi +1 202 555 0123', 'PHONE_NUMBER'),
            ('Gọi ٠٩١٢٣٤٥٦٧٨', 'PHONE_NUMBER'),
            ('Số bàn (028) 1234 5678', 'PHONE_NUMBER'),
            ('Gọi ０９１２３４５６７８', 'PHONE_NUMBER'),
            ('Số em 09\u200b12-345-678', 'PHONE_NUMBER'),
            ('Gọi em không chín một hai ba bốn năm sáu bảy tám', 'PHONE_NUMBER'),
            ('Mail em lan @ example . com', 'EMAIL_ADDRESS'),
            ('Gửi lan[at]example[dot]com', 'EMAIL_ADDRESS'),
            ('Ghé https://t.me/lan_clean', 'EXTERNAL_CONTACT'),
            ('facebook.com/lan.clean', 'EXTERNAL_CONTACT'),
            ('Zalo: lan.clean', 'EXTERNAL_CONTACT'),
            ('Telegram của chị là @lan_clean', 'EXTERNAL_CONTACT'),
            ('Chuyển vào STK 123456789012 ngân hàng ACB giúp em', 'OFF_PLATFORM_PAYMENT'),
            ('Lan oi thue rieng em nhe', 'OFF_PLATFORM_SOLICITATION'),
            ('Hủy đơn rồi chị đặt trực tiếp với em nhé', 'OFF_PLATFORM_SOLICITATION'),
        )
        for text, category in cases:
            with self.subTest(text=text):
                violation = detect_violation(text)
                self.assertIsNotNone(violation)
                self.assertEqual(violation.category, category)

    def test_work_information_and_negations(self):
        cases = (
            'Ngày 09/10 em đến 10:30 phòng 901 tầng 9 diện tích 120m2',
            'Giá 500000 đồng, mã đơn CW0912345678',
            'Mã đơn CW0912345678 cần dọn lúc 08:00',
            'Phòng 1205 ở 456 Lê Lợi, nhà rộng 90 m2',
            'Ứng dụng hỗ trợ Facebook và Zalo chứ?',
            'Đừng kết bạn Facebook em nhé',
            'Chị không muốn đặt trực tiếp với em đâu',
            'Chị đừng chuyển khoản trực tiếp vào tài khoản cá nhân của em',
            'Chị không thuê riêng em cho rẻ nhé',
            'Không hủy đơn trên app rồi thuê riêng em nhé',
            'Đừng giao dịch ngoài nền tảng cho tiết kiệm',
            'Chị đừng đặt trực tiếp với em khỏi qua app',
            'Em không được nhận chuyển tiền riêng từ khách',
            'Chị hủy vì sai địa chỉ rồi đặt lại trong CleanWise',
            'Đơn này thanh toán tiền mặt, chị thanh toán trực tiếp cho em theo đơn nhé',
            'Chị trả tiền mặt theo đơn sau khi dọn xong',
            'Dọn riêng phòng ngủ trước rồi dọn bếp',
            'Ngân hàng ACB, STK 0912345678 đã được cập nhật',
            'Đừng chuyển vào STK 123456789012 ngân hàng ACB',
            'Trang hướng dẫn example.com/facebook.com/faq',
            'Facebook.com.evil.example là tên miền giả mạo',
        )
        for text in cases:
            with self.subTest(text=text):
                self.assertIsNone(detect_violation(text))

    def test_safe_context_cannot_exempt_violation(self):
        cases = (
            'Địa chỉ nhà 123 Lê Lợi, gọi 0912.345.678 nhé',
            'Đừng thuê riêng nhé. Chị chuyển tiền riêng cho em',
            'Chị thanh toán trên app; lần sau thuê riêng em nhé',
            'Đừng đặt qua app nữa cứ thuê riêng em',
            'Không được chia sẻ số điện thoại. Số em 0912345678',
            'Không được chia sẻ số điện thoại\nSố em 0912345678',
            'STK 123456789012 ngân hàng ACB, gọi em 0912345678',
            'Đừng thuê riêng, nhưng lần tới mình làm riêng cho tiện nha',
            'Không hủy đơn trên app; nhưng chuyển tiền riêng cho em nhé',
        )
        for text in cases:
            with self.subTest(text=text):
                self.assertIsNotNone(detect_violation(text))

    def test_cosine_catches_variant_and_preserves_safe_contrast(self):
        violation = detect_violation('Lần tới mình làm riêng cho tiện nha')
        self.assertIsNotNone(violation)
        self.assertEqual(violation.method, 'cosine')
        self.assertIsNone(detect_violation('Đừng làm riêng, hãy đặt lịch trong ứng dụng'))

    def test_long_clause_keeps_private_invitation_visible(self):
        text = ('Chị ơi hôm nay em mang đủ dụng cụ và đến đúng giờ '
                'lần tới mình làm riêng cho tiện nha để chị tiết kiệm thời gian')
        violation = detect_violation(text)
        self.assertIsNotNone(violation)
        self.assertEqual(violation.method, 'cosine')
        self.assertEqual(violation.category, 'OFF_PLATFORM_SOLICITATION')

    def test_lower_threshold_catches_variant_previously_below_cutoff(self):
        text = 'Lần tới mình làm riêng cho tiện nha chị ơi'
        with override_settings(CHAT_MODERATION_COSINE_THRESHOLD=0.65):
            self.assertIsNone(detect_violation(text))
        with override_settings(CHAT_MODERATION_COSINE_THRESHOLD=0.55):
            violation = detect_violation(text)
            self.assertIsNotNone(violation)
            self.assertEqual(violation.method, 'cosine')

    def test_chunks_preserve_negation_and_booking_payment_context(self):
        for text in (
            'Chị ơi hôm nay em mang đủ dụng cụ và đến đúng giờ đừng làm riêng cho tiện nha hãy đặt trên ứng dụng',
            'Chị ơi em đã dọn xong phòng bếp và phòng ngủ đơn tiền mặt chị thanh toán trực tiếp cho em theo đơn trên app',
            'Hôm nay em mang đầy đủ dụng cụ để làm riêng phòng bếp trước sau đó dọn phòng ngủ và ban công giúp chị',
            'Chị xem hướng dẫn trên ứng dụng để biết Facebook có hỗ trợ đăng nhập tài khoản hay không nhé',
        ):
            with self.subTest(text=text):
                self.assertIsNone(detect_violation(text))

    def test_chunk_boundaries_overlap_without_tiny_fragments(self):
        clause = ' '.join(str(index) for index in range(25))
        chunks = list(cosine_chunks(clause))
        self.assertEqual(chunks[0], clause)
        self.assertEqual(chunks[1].split()[6:], chunks[2].split()[:6])
        self.assertTrue(all(6 <= len(chunk.split()) <= 12 for chunk in chunks[1:]))
        self.assertEqual(list(cosine_chunks('Nhắn trong ứng dụng nhé')), ['Nhắn trong ứng dụng nhé'])

    @override_settings(CHAT_MODERATION_COSINE_THRESHOLD=1.0)
    def test_threshold_is_configurable(self):
        self.assertIsNone(detect_violation('Lần tới mình làm riêng cho tiện nha'))
        self.assertIsNotNone(detect_violation('Gọi 0912345678'))

    def test_index_is_cached_and_unicode_is_normalized(self):
        self.assertIs(reference_index(), reference_index())
        self.assertEqual(normalize_text('  ĐẶT\u200b RIÊNG  '), 'dat rieng')
