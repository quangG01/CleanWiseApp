from django.http import FileResponse, Http404
from rest_framework.permissions import AllowAny
from rest_framework.views import APIView

from .help_content import IMAGE_NAME, IMAGE_ROOT


class HelpImageView(APIView):
    """Serve only bundled, public guide screenshots, never user-uploaded media."""
    authentication_classes = []
    permission_classes = [AllowAny]

    def get(self, request, name):
        if not IMAGE_NAME.fullmatch(name):
            raise Http404
        path = IMAGE_ROOT / name
        if not path.is_file():
            raise Http404
        response = FileResponse(path.open('rb'), content_type='image/jpeg' if name.endswith('.jpg') else 'image/png')
        response['Cache-Control'] = 'public, max-age=86400'
        response['X-Content-Type-Options'] = 'nosniff'
        return response
