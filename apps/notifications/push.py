import requests

EXPO_PUSH_URL = 'https://exp.host/--/api/v2/push/send'


def send_push_to_user(user, title, message, data=None):
    tokens = list(user.device_tokens.values_list('token', flat=True))
    if not tokens:
        return

    messages = [
        {
            'to': token,
            'title': title,
            'body': message,
            'data': data or {},
            'sound': 'default',
        }
        for token in tokens
    ]

    try:
        requests.post(EXPO_PUSH_URL, json=messages, timeout=5)
    except requests.RequestException:
        pass