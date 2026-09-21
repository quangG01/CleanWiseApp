import requests
from django.core.cache import cache


VIETQR_BANKS_URL = 'https://api.vietqr.io/v2/banks'
CACHE_KEY = 'payments:vietqr-bank-catalog:v1'
CACHE_TIMEOUT_SECONDS = 60 * 60 * 24

FALLBACK_BANKS = [
    {'id': 17, 'name': 'Ngân hàng TMCP Ngoại Thương Việt Nam', 'code': 'VCB', 'bin': '970436', 'short_name': 'Vietcombank', 'logo': '', 'transfer_supported': True, 'lookup_supported': False},
    {'id': 43, 'name': 'Ngân hàng TMCP Đầu tư và Phát triển Việt Nam', 'code': 'BIDV', 'bin': '970418', 'short_name': 'BIDV', 'logo': '', 'transfer_supported': True, 'lookup_supported': False},
    {'id': 4, 'name': 'Ngân hàng TMCP Công thương Việt Nam', 'code': 'ICB', 'bin': '970415', 'short_name': 'VietinBank', 'logo': '', 'transfer_supported': True, 'lookup_supported': False},
    {'id': 5, 'name': 'Ngân hàng TMCP Quân đội', 'code': 'MB', 'bin': '970422', 'short_name': 'MBBank', 'logo': '', 'transfer_supported': True, 'lookup_supported': False},
    {'id': 2, 'name': 'Ngân hàng TMCP Á Châu', 'code': 'ACB', 'bin': '970416', 'short_name': 'ACB', 'logo': '', 'transfer_supported': True, 'lookup_supported': False},
    {'id': 6, 'name': 'Ngân hàng TMCP Kỹ thương Việt Nam', 'code': 'TCB', 'bin': '970407', 'short_name': 'Techcombank', 'logo': '', 'transfer_supported': True, 'lookup_supported': False},
]


def _normalize_bank(bank):
    return {
        'id': bank.get('id'),
        'name': bank.get('name', ''),
        'code': bank.get('code', ''),
        'bin': str(bank.get('bin', '')),
        'short_name': bank.get('shortName') or bank.get('short_name') or bank.get('code', ''),
        'logo': bank.get('logo', ''),
        'transfer_supported': bool(bank.get('transferSupported', bank.get('transfer_supported', False))),
        'lookup_supported': bool(bank.get('lookupSupported', bank.get('lookup_supported', False))),
    }


def get_bank_catalog():
    cached = cache.get(CACHE_KEY)
    if cached:
        return cached

    try:
        response = requests.get(VIETQR_BANKS_URL, timeout=5)
        response.raise_for_status()
        payload = response.json()
        banks = payload.get('data') or []
        if not banks:
            raise ValueError('VietQR returned an empty bank catalog.')
        normalized = sorted(
            (_normalize_bank(bank) for bank in banks),
            key=lambda bank: bank['short_name'].lower(),
        )
        cache.set(CACHE_KEY, normalized, CACHE_TIMEOUT_SECONDS)
        return normalized
    except (requests.RequestException, ValueError, TypeError):
        fallback = sorted(FALLBACK_BANKS, key=lambda bank: bank['short_name'].lower())
        cache.set(CACHE_KEY, fallback, 60 * 15)
        return fallback
