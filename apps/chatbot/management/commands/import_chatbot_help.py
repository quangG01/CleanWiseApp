import json
from pathlib import Path
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from apps.chatbot.models import HelpArticle


class Command(BaseCommand):
    help = 'Nhập bốn hướng dẫn CleanWise. Mặc định bản nháp; --publish để xuất bản nội dung đã duyệt.'

    def add_arguments(self, parser):
        parser.add_argument('--publish', action='store_true')
        parser.add_argument('--path', type=Path, default=Path(__file__).resolve().parents[2] / 'data' / 'help_articles.json')

    @transaction.atomic
    def handle(self, *args, **options):
        try:
            items = json.loads(options['path'].read_text(encoding='utf-8'))
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
