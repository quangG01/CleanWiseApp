"""Contact redaction with offsets back into the original Unicode message."""
import re
import unicodedata
from urllib.parse import urlsplit

from django.conf import settings

from .moderation import PHONE_CANDIDATE, SPOKEN_NUMBER, DIGIT_WORDS, CONTACT_CONTEXT, is_phone


EMAIL = re.compile(r'(?<![\w.+-])[\w.+-]+\s*(?:@|\[at\])\s*(?:[a-z0-9-]+\s*(?:\.|\[dot\])\s*)+[a-z]{2,}(?!\w)')
URL = re.compile(
    r'(?<![\w@])(?:[a-z][a-z0-9+.-]*://[^\s<>]+|'
    r'(?:www\.)?(?:[\w](?:[\w-]*[\w])?\.)+[a-z]{2,63}'
    r'(?::\d+)?(?:[/?#][^\s<>]*)?)(?!\w)', re.IGNORECASE,
)
LABELS = {'PHONE_NUMBER': '[SĐT đã ẩn]', 'EMAIL_ADDRESS': '[Email đã ẩn]', 'EXTERNAL_LINK': '[Liên kết đã ẩn]'}


def normalized_with_offsets(message):
    chars, offsets = [], []
    for index, char in enumerate(message):
        value = unicodedata.normalize('NFKC', char).casefold().replace('đ', 'd')
        for part in unicodedata.normalize('NFD', value):
            if unicodedata.category(part) in ('Mn', 'Cf'):
                continue
            chars.append(str(unicodedata.decimal(part)) if part.isdecimal() else (' ' if part.isspace() else part))
            offsets.append(index)
    return ''.join(chars), offsets


def allowed_url(value):
    try:
        value = unicodedata.normalize('NFKC', value)
        parsed = urlsplit(value if '://' in value else 'https://' + value)
        # Only explicitly configured, exact HTTP(S) hosts are trusted.
        return (parsed.scheme in ('http', 'https') and not parsed.username and not parsed.password
                and parsed.hostname in getattr(settings, 'CHAT_ALLOWED_LINK_HOSTS', ()))
    except ValueError:
        return False


def redact_contacts(message):
    text, offsets = normalized_with_offsets(message)
    spans = []

    def add(match, category):
        start, end = match.span()
        if not any(start < right and end > left for left, right, _ in spans):
            spans.append((start, end, category))

    for match in URL.finditer(text):
        # The search copy folds accents; host trust must use the original value
        # so a lookalike such as cléanwise.vn cannot inherit cleanwise.vn's trust.
        original_url = message[offsets[match.start()]:offsets[match.end() - 1] + 1]
        if not allowed_url(original_url.rstrip('.,;!?)')):
            add(match, 'EXTERNAL_LINK')
    for match in EMAIL.finditer(text):
        add(match, 'EMAIL_ADDRESS')
    for match in PHONE_CANDIDATE.finditer(text):
        digits = re.sub(r'\D', '', match.group())
        account = re.search(r'\b(?:stk|so tai khoan)\s*[:=]?\s*$', text[:match.start()])
        international = match.group().startswith('+') and digits[0] != '0' and 9 <= len(digits) <= 15
        if not account and (is_phone(digits) or international):
            add(match, 'PHONE_NUMBER')
    if CONTACT_CONTEXT.search(text):
        for match in SPOKEN_NUMBER.finditer(text):
            digits = ''.join(DIGIT_WORDS[word] for word in re.findall(r'\w+', match.group()))
            if is_phone(digits):
                add(match, 'PHONE_NUMBER')

    categories = sorted({category for _, _, category in spans})
    has_content = text
    redacted = message
    for start, end, category in sorted(spans, reverse=True):
        redacted = redacted[:offsets[start]] + LABELS[category] + redacted[offsets[end - 1] + 1:]
        has_content = has_content[:start] + has_content[end:]
    return redacted, categories, bool(re.search(r'\w', has_content))
