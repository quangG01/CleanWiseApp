"""Local text moderation: deterministic rules and cached TF-IDF cosine.

No network calls, learned classifier, raw-message logging or extra dependencies.
Only participant-authored text is checked; system notices bypass this service.
"""

import math
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache

from django.conf import settings
from rest_framework.exceptions import APIException

from .moderation_samples import ALLOWED_SAMPLES, VIOLATION_SAMPLES


BLOCK_CODE = 'CHAT_CONTENT_BLOCKED'
MESSAGES = {
    'PHONE_NUMBER': 'Tin nhắn chứa số điện thoại.',
    'EMAIL_ADDRESS': 'Tin nhắn chứa địa chỉ email.',
    'EXTERNAL_CONTACT': 'Tin nhắn chứa thông tin hoặc lời mời liên hệ ngoài CleanWise.',
    'OFF_PLATFORM_PAYMENT': 'Tin nhắn chứa yêu cầu thanh toán riêng ngoài CleanWise.',
    'OFF_PLATFORM_SOLICITATION': 'Tin nhắn chứa lời mời giao dịch ngoài CleanWise.',
}


@dataclass(frozen=True)
class Violation:
    category: str
    method: str

    @property
    def message(self):
        return MESSAGES[self.category] + ' Vui lòng chỉnh sửa nội dung để tiếp tục.'


class ChatContentBlocked(APIException):
    status_code = 400
    default_code = BLOCK_CODE

    def __init__(self, violation):
        super().__init__({
            'code': BLOCK_CODE,
            'violation_type': violation.category,
            'message': violation.message,
        })


def normalize_text(text):
    text = unicodedata.normalize('NFKC', text).casefold()
    text = ''.join(char for char in text if unicodedata.category(char) != 'Cf')
    text = ''.join(str(unicodedata.decimal(char)) if char.isdecimal() else char for char in text)
    text = unicodedata.normalize('NFD', text.replace('đ', 'd'))
    text = ''.join(char for char in text if unicodedata.category(char) != 'Mn')
    text = re.sub(r'\s+', ' ', text).strip()
    # Canonicalize common split spellings before both rules and cosine scoring.
    # Contextual rules still decide whether this is an external-contact request.
    return re.sub(r'\bface[\s._-]+book\b', 'facebook', text)


PHONE_CANDIDATE = re.compile(r'(?<![\w+])\+?\d(?:[\s.()\-]*\d){8,14}(?![\w])')
EMAIL = re.compile(r'(?<![\w.+-])[\w.+-]+\s*@\s*(?:[a-z0-9-]+\s*\.\s*)+[a-z]{2,}(?!\w)')
SOCIAL_LINK = re.compile(
    r'(?<![\w./-])(?:https?://)?(?:www\.|m\.)?'
    r'(?:zalo\.me|facebook\.com|fb\.com|fb\.me|m\.me|messenger\.com|'
    r't\.me|telegram\.me|telegram\.dog|instagram\.com|wa\.me|api\.whatsapp\.com)'
    r'(?=[:/\s?#]|$)'
)
CONTACT_CONTEXT = re.compile(r'\b(?:sdt|so dien thoai|so di dong|goi|lien he|zalo)\b')
DIGIT_WORDS = {'khong': '0', 'mot': '1', 'hai': '2', 'ba': '3', 'bon': '4',
               'tu': '4', 'nam': '5', 'sau': '6', 'bay': '7', 'tam': '8', 'chin': '9'}
SPOKEN_NUMBER = re.compile(r'\b(?:' + '|'.join(DIGIT_WORDS) + r')(?:[\s,.-]+(?:' + '|'.join(DIGIT_WORDS) + r')){8,10}\b')
BANK_CONTEXT = re.compile(r'\b(?:stk|so tai khoan|tai khoan ngan hang|vietcombank|'
                          r'techcombank|mbbank|vietinbank|bidv|agribank|acb|vpbank|tpbank|sacombank)\b')
BANK_NUMBER = re.compile(r'(?<!\w)\d(?:[\s.-]*\d){5,19}(?!\w)')
PAYMENT_REQUEST = re.compile(r'\b(?:chuyen(?: tien| khoan| thang)?|tra tien|thanh toan|gui tien)\b')

# Match phrases rather than isolated words. Negation is checked per match.
RULES = (
    ('EXTERNAL_CONTACT', re.compile(
        r'\b(?:ket ban (?:zalo|facebook)|'
        r'(?:nhan|nhan tin|lien he|trao doi) (?:rieng )?(?:qua|tren) (?:zalo|facebook|telegram|messenger|whatsapp)|'
        r'(?:cho|gui)(?: \w+){0,3} (?:so dien thoai|so di dong|sdt)|'
        r'(?:zalo|facebook|telegram|instagram|whatsapp)(?: cua)? (?:em|chi|anh|toi|minh) (?:la|ten)|'
        r'(?:tai khoan|nick|username) (?:zalo|facebook|telegram|instagram)|'
        r'(?:zalo|facebook|telegram|instagram)\s*[:=]\s*\S+|'
        r'(?:zalo|facebook|telegram|instagram)(?: \w+){0,3}\s+@[\w.]+)\b'
    )),
    ('OFF_PLATFORM_PAYMENT', re.compile(
        r'\b(?:(?:chuyen(?: tien| khoan)?|tra(?: tien)?|thanh toan|dua tien mat)(?: \w+){0,3} rieng|'
        r'chuyen(?: tien| khoan)? (?:thang|truc tiep) (?:cho|vao)|'
        r'thanh toan (?:ngoai app|ngoai ung dung|ngoai he thong)|'
        r'(?:tra|thanh toan)(?: \w+){0,4} (?:khong can|khoi) (?:qua|tren) (?:app|cleanwise))\b'
    )),
    ('OFF_PLATFORM_SOLICITATION', re.compile(
        r'\b(?:(?:dat|thue|goi|hen don)(?: \w+){0,2} rieng (?:em|chi|anh|toi|minh)|'
        r'(?:dat|thue) truc tiep (?:voi )?(?:em|chi|anh)|'
        r'(?:lam|thue|dat|giao dich) (?:ngoai app|ngoai ung dung|ngoai nen tang|ngoai he thong)|'
        r'bo qua (?:app|cleanwise|he thong)|'
        r'(?:khoi|khong can) (?:dat |thue )?(?:qua|tren) (?:app|cleanwise|ung dung))\b'
    )),
)

ACTION = r'(?:dat|thue|goi|chuyen|tra|thanh toan|gui|cho|chia se|ket ban|nhan tin|lien he|lam rieng|giao dich|huy|bo qua)'
NEGATION = r'(?:dung|khong(?: (?:duoc|nen|muon|nhan))?|cam|bi cam|bao cao loi moi)'
NEGATED_ACTION = re.compile(r'\b' + NEGATION + r'(?: (?:anh|chi|em|minh|toi|nhan))?\s+' + ACTION + r'\b')


def is_negated(text, start):
    # Negation can govern a sequence ("đừng hủy ... rồi thuê riêng ...").
    # Commas/contrast markers delimit this scope in detect_violation.
    prefix = text[:start].rsplit(',', 1)[-1]
    if re.search(r'\b' + NEGATION + r'(?: (?:anh|chi|em|minh|toi|nhan))?\s+$', prefix):
        return True
    return any(len(prefix[match.end():].split()) <= 12 for match in NEGATED_ACTION.finditer(prefix))


def is_phone(digits):
    if digits.startswith('84'):
        digits = '0' + digits[2:]
    return bool(re.fullmatch(r'(?:0[35789]\d{8}|02\d{9})', digits))


def _features(text):
    words = re.findall(r'\b\w+\b', text)
    return Counter(' '.join(words[index:index + size])
                   for size in (1, 2, 3)
                   for index in range(len(words) - size + 1))


def cosine_chunks(clause):
    """Keep the whole clause and overlapping windows for long clauses.

    Negation is checked on the original clause before any windows are scored,
    so trimming a prefix cannot turn a warning into an invitation.
    """
    yield clause
    words = re.findall(r'\b\w+\b', clause)
    if len(words) <= 12:
        return
    for start in range(0, len(words) - 5, 6):
        yield ' '.join(words[start:start + 12])


class ReferenceIndex:
    """Smoothed IDF, sublinear TF and L2 normalization over word 1–3 grams."""

    def __init__(self):
        samples = [text for _, text in VIOLATION_SAMPLES] + list(ALLOWED_SAMPLES)
        documents = [_features(normalize_text(text)) for text in samples]
        frequency = Counter(feature for document in documents for feature in document)
        self.idf = {feature: math.log((1 + len(documents)) / (1 + count)) + 1
                    for feature, count in frequency.items()}
        self.vectors = tuple(self.vector(document) for document in documents)

    def vector(self, features):
        weights = {feature: (1 + math.log(count)) * self.idf[feature]
                   for feature, count in features.items() if feature in self.idf}
        norm = math.sqrt(sum(weight * weight for weight in weights.values()))
        return {feature: weight / norm for feature, weight in weights.items()} if norm else {}

    def scores(self, text):
        features = _features(text)
        # Avoid treating a few known words in an otherwise unknown sentence as
        # strong evidence. There must be at least two known phrase features.
        if sum(' ' in feature and feature in self.idf for feature in features) < 2:
            return None, 0.0, 0.0
        query = self.vector(features)
        scores = [sum(weight * reference.get(feature, 0.0) for feature, weight in query.items())
                  for reference in self.vectors]
        blocked = scores[:len(VIOLATION_SAMPLES)]
        best = max(range(len(blocked)), key=blocked.__getitem__)
        return VIOLATION_SAMPLES[best][0], blocked[best], max(scores[len(blocked):])


@lru_cache(maxsize=1)
def reference_index():
    return ReferenceIndex()


def detect_violation(message):
    text = normalize_text(message)
    email_text = re.sub(r'\s*\[at\]\s*', '@', text)
    email_text = re.sub(r'\s*\[dot\]\s*', '.', email_text)
    if EMAIL.search(email_text):
        return Violation('EMAIL_ADDRESS', 'regex')
    if SOCIAL_LINK.search(text):
        return Violation('EXTERNAL_CONTACT', 'regex')

    for candidate in PHONE_CANDIDATE.finditer(text):
        digits = re.sub(r'\D', '', candidate.group())
        labelled_account = re.search(r'\b(?:stk|so tai khoan)\s*[:=]?\s*$', text[:candidate.start()])
        international = candidate.group().startswith('+') and digits[0] != '0' and 9 <= len(digits) <= 15
        if (is_phone(digits) or international) and not labelled_account:
            return Violation('PHONE_NUMBER', 'regex')

    # Inspect each clause, so a safe sentence cannot exempt a later violation.
    sentences = re.split(r'[!?;]|\.(?!\d)', normalize_text(message.replace('\n', ';')))
    clauses = [clause for sentence in sentences
               for clause in re.split(
                   r',|\b(?:nhung|tuy nhien|cu|hay)\b|\b(?:ma|nen) (?=(?:anh|chi|em|minh|toi)\b)',
                   sentence,
               )]
    for clause in clauses:
        bank = BANK_CONTEXT.search(clause)
        request = PAYMENT_REQUEST.search(clause)
        if bank and BANK_NUMBER.search(clause) and request and not is_negated(clause, request.start()):
            return Violation('OFF_PLATFORM_PAYMENT', 'regex')
        if CONTACT_CONTEXT.search(clause):
            for candidate in SPOKEN_NUMBER.finditer(clause):
                digits = ''.join(DIGIT_WORDS[word] for word in re.findall(r'\w+', candidate.group()))
                if is_phone(digits):
                    return Violation('PHONE_NUMBER', 'regex')
        for category, pattern in RULES:
            if any(not is_negated(clause, match.start()) for match in pattern.finditer(clause)):
                return Violation(category, 'regex')

        # A lexical match must not override an explicit negated action in the
        # same clause. PII above is still blocked, even in a quoted warning.
        if NEGATED_ACTION.search(clause):
            continue
        index = reference_index()
        _, _, context_allowed_score = index.scores(clause)
        threshold = float(getattr(settings, 'CHAT_MODERATION_COSINE_THRESHOLD', 0.4))
        margin = float(getattr(settings, 'CHAT_MODERATION_COSINE_MARGIN', 0.12))
        for chunk in cosine_chunks(clause):
            category, blocked_score, allowed_score = index.scores(chunk)
            # A window must not discard evidence that the original clause is
            # ordinary work/payment according to an existing booking.
            allowed_score = max(allowed_score, context_allowed_score)
            if category and blocked_score >= threshold and blocked_score - allowed_score >= margin:
                return Violation(category, 'cosine')
    return None


def validate_chat_content(message):
    violation = detect_violation(message)
    if violation:
        raise ChatContentBlocked(violation)
