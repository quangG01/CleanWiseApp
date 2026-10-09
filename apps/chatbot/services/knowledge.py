import re
import unicodedata
from django.utils import timezone
from django.db.models import Q
from ..models import HelpArticle


def published_articles():
    today = timezone.localdate()
    return HelpArticle.objects.filter(status=HelpArticle.Status.PUBLISHED, role='CUSTOMER',
                                      effective_from__lte=today).filter(
        Q(effective_until__isnull=True) | Q(effective_until__gte=today))


def normalize(text):
    text = unicodedata.normalize('NFD', text.lower().replace('đ', 'd'))
    return re.sub(r'[^a-z0-9 ]', ' ', ''.join(c for c in text if not unicodedata.combining(c)))


STOP = set('toi cua la va thi co khong nhu nao lam sao cho voi mot cac duoc ban hay gi ve nay minh xin muon can the'.split())
ALIASES = {'vietqr': 'chuyen khoan qr', 'voucher': 'ma giam gia', 'topup': 'nap tien',
           'booking': 'dat don', 'cash': 'tien mat', 'wallet': 'vi', 'refund': 'hoan tien'}


def search_help(query, limit=4):
    query = normalize(query)
    for term, expansion in ALIASES.items():
        if term in query.split():
            query += ' ' + expansion
    tokens = set(query.split()) - STOP
    if not tokens:
        return {'results': [], 'detail': 'Chưa có nguồn phù hợp. Hãy hỏi rõ chủ đề cần hướng dẫn.'}, []
    ranked = []
    for article in published_articles():
        for index, section in enumerate(article.sections):
            heading = normalize(section['heading'])
            body = normalize(section['text'])
            matched = tokens & set((heading + ' ' + body).split())
            # Require enough query coverage; a single generic word is not evidence.
            coverage = len(matched) / len(tokens)
            if not matched or coverage < 0.45 or (len(tokens) > 1 and len(matched) < 2):
                continue
            score = coverage * 10 + len(tokens & set(heading.split())) * 2
            ranked.append((score, article.pk, index, article, section))
    ranked.sort(key=lambda row: (-row[0], row[1], row[2]))
    results, refs = [], []
    for _, _, index, article, section in ranked[:limit]:
        results.append({'article_id': article.pk, 'title': article.title, 'version': article.version,
                        'effective_from': article.effective_from.isoformat(), 'source_document': article.source_document,
                        'section': section['heading'], 'text': section['text']})
        ref = {'type': 'help', 'id': article.pk}
        if ref not in refs:
            refs.append(ref)
    return {'results': results, 'detail': '' if results else 'Không tìm thấy nguồn đã xuất bản đủ phù hợp. Không suy diễn chính sách.'}, refs
