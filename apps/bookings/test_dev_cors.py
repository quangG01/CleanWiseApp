from django.test import SimpleTestCase, override_settings

from core.settings.dev import CORS_ALLOW_HEADERS


@override_settings(CORS_ALLOW_HEADERS=CORS_ALLOW_HEADERS, CORS_ALLOW_ALL_ORIGINS=True)
class DevelopmentInvitationCorsTests(SimpleTestCase):
    def test_invitation_preflight_allows_idempotency_header(self):
        response = self.client.options(
            '/api/admin/schedules/bulk-assign/',
            HTTP_ORIGIN='http://localhost:3000',
            HTTP_ACCESS_CONTROL_REQUEST_METHOD='POST',
            HTTP_ACCESS_CONTROL_REQUEST_HEADERS='authorization,content-type,idempotency-key',
        )
        self.assertEqual(response.status_code, 200)
        allowed = {header.strip().lower() for header in response['Access-Control-Allow-Headers'].split(',')}
        self.assertTrue({'authorization', 'content-type', 'idempotency-key'} <= allowed)
