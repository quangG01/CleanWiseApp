"""Validate optional illustrated steps while retaining plain-text RAG sources."""
import re
from pathlib import Path

from django.core.exceptions import ValidationError


IMAGE_ROOT = Path(__file__).resolve().parent / 'data' / 'guide_images'
IMAGE_NAME = re.compile(r'[a-z0-9][a-z0-9-]{0,100}\.(?:png|jpg)\Z')
SECTION_ID = re.compile(r'[a-z0-9]+(?:-[a-z0-9]+)*\Z')


def validate_guide_sections(sections):
    seen = set()
    for section in sections:
        identifier = section.get('id')
        if identifier is not None:
            if not isinstance(identifier, str) or not SECTION_ID.fullmatch(identifier) or identifier in seen:
                raise ValidationError({'sections': 'Mã đề mục phải hợp lệ và không trùng lặp.'})
            seen.add(identifier)
        steps = section.get('steps')
        if steps is None:
            continue
        if not identifier or not isinstance(steps, list) or not 1 <= len(steps) <= 20:
            raise ValidationError({'sections': 'Đề mục minh họa cần mã đề mục và 1–20 bước.'})
        for step in steps:
            if not isinstance(step, dict) or any(not isinstance(step.get(k), str) or not step[k].strip()
                                                 or len(step[k]) > 4000 for k in ('title', 'text')):
                raise ValidationError({'sections': 'Mỗi bước cần tiêu đề và nội dung văn bản.'})
            image = step.get('image')
            if image is None:
                continue
            if (not isinstance(image, dict) or not isinstance(image.get('file'), str)
                    or not IMAGE_NAME.fullmatch(image['file']) or not (IMAGE_ROOT / image['file']).is_file()
                    or any(type(image.get(k)) is not int or not 1 <= image[k] <= 10000 for k in ('width', 'height'))
                    or not isinstance(image.get('alt'), str) or not image['alt'].strip()):
                raise ValidationError({'sections': 'Ảnh hướng dẫn phải là ảnh PNG/JPG có sẵn, có kích thước và mô tả.'})
            markers = image.get('markers', [])
            if not isinstance(markers, list) or len(markers) > 5:
                raise ValidationError({'sections': 'Mỗi ảnh có tối đa 5 vị trí đánh dấu.'})
            for marker in markers:
                if (not isinstance(marker, dict)
                        or any(type(marker.get(k)) not in (int, float) or not 0 <= marker[k] <= 100
                               for k in ('x', 'y', 'width', 'height'))
                        or marker['width'] <= 0 or marker['height'] <= 0
                        or marker['x'] + marker['width'] > 100 or marker['y'] + marker['height'] > 100):
                    raise ValidationError({'sections': 'Vị trí đánh dấu phải nằm trong ảnh.'})
