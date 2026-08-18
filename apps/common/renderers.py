from rest_framework.renderers import JSONRenderer
from datetime import datetime

class CustomJSONRenderer(JSONRenderer):
    """
    Custom JSON Renderer xử lý cho toàn bộ Response THÀNH CÔNG (200, 201...).
    """
    def render(self, data, accepted_media_type=None, renderer_context=None):
        response = renderer_context.get('response') if renderer_context else None

        
        if response and response.status_code >= 400:
            return super().render(data, accepted_media_type, renderer_context)

        
        status_code = response.status_code if response else 200
        message = "Call API thành công"

        
        if isinstance(data, dict):
            if 'message' in data and len(data) == 1:
                message = data['message']
                data = None
            elif 'message' in data:
                message = data.pop('message')

        custom_response = {
            "success": True,
            "status_code": status_code,
            "message": message,
            "data": data,
            "timestamp": datetime.now().isoformat()
        }

        return super().render(custom_response, accepted_media_type, renderer_context)