import json
from pathlib import Path
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from apps.chatbot.models import HelpArticle

DATA_ROOT = Path(__file__).resolve().parents[2] / 'data'
DEFAULT_PATH = DATA_ROOT / 'help_articles.json'


class Command(BaseCommand):
    help = 'Nhập hướng dẫn CleanWise. Mặc định bản nháp; --publish để xuất bản nội dung đã duyệt.'

    def add_arguments(self, parser):
        parser.add_argument('--publish', action='store_true')
        parser.add_argument('--path', type=Path, default=DEFAULT_PATH)

    @transaction.atomic
    def handle(self, *args, **options):
        try:
            items = json.loads(options['path'].read_text(encoding='utf-8'))
            if options['path'] == DEFAULT_PATH:
                for name in ('customer_app_guide.json', 'customer_payment_guide.json', 'customer_booking_guide.json'):
                    items += json.loads((DATA_ROOT / name).read_text(encoding='utf-8'))
                # Dedicated illustrated chapters supersede the legacy outline.
                # Import only the latest bundled revision so a repeat default
                # import never attempts to republish a retired legacy revision.
                latest = {}
                for item in items:
                    previous = latest.get(item['slug'])
                    if previous is None or item['version'] > previous['version']:
                        latest[item['slug']] = item
                    elif item['version'] == previous['version'] and item != previous:
                        raise CommandError(f"{item['slug']} v{item['version']} bị trùng với nội dung khác.")
                items = list(latest.values())
            for item in items:
                slug, version = item['slug'], item['version']
                article = HelpArticle.objects.filter(slug=slug, version=version).first()
                if article:
                    for name, value in item.items():
                        current = getattr(article, name)
                        if name == 'effective_from':
                            current = current.isoformat()
                        if current != value:
                            raise CommandError(f'{slug} v{version} đã có nội dung khác. Tăng version để nhập bản mới.')
                else:
                    article = HelpArticle(**item)
                if options['publish']:
                    article.status = HelpArticle.Status.PUBLISHED
                article.save()
                self.stdout.write(f'{slug} v{version}: {article.status}')
        except (ValueError, KeyError, OSError) as exc:
            raise CommandError(str(exc)) from exc
