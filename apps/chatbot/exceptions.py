from rest_framework.exceptions import APIException


class ChatbotError(APIException):
    def __init__(self, message, *, code='CHATBOT_UNAVAILABLE', status_code=503):
        self.status_code = status_code
        super().__init__({'detail': message, 'chatbot_error_code': code})


class AgentUnavailable(Exception):
    pass
