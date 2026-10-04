"""
Test nhanh nạp + rút ví qua API. Chạy được cả khi mock lẫn khi đã nối payOS thật.

Cách dùng (server đang chạy, có token đăng nhập của khách hoặc nhân viên):

  # Mock (chưa có payOS): tự giả lập thanh toán
  python wallet_smoke_test.py --token <JWT>

  # Nhân viên
  python wallet_smoke_test.py --token <JWT> --role worker

  # payOS thật: script in link, bạn tự quét QR thanh toán, script chờ tới khi tiền vào ví
  python wallet_smoke_test.py --token <JWT> --mode real --topup 50000 --withdraw 50000

Tài khoản test cần đã lưu 1 tài khoản ngân hàng nhận tiền.
Mock: đuôi số tài khoản quyết định kết quả (xem HUONG_DAN.md).
"""
import argparse
import sys
import time
import uuid

import requests

results = []


def find(obj, key):
    """Tìm giá trị theo key trong JSON lồng nhau (đề phòng renderer bọc thêm tầng)."""
    if isinstance(obj, dict):
        if key in obj:
            return obj[key]
        for v in obj.values():
            found = find(v, key)
            if found is not None:
                return found
    return None


def check(name, ok, detail=''):
    results.append(bool(ok))
    print(f"  [{'OK ' if ok else 'LỖI'}] {name}" + (f"  ->  {detail}" if detail else ''))
    return ok


class Api:
    def __init__(self, base, token, role):
        self.base = base.rstrip('/') + f'/api/{role}/wallet'
        self.h = {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}

    def get(self, path):
        r = requests.get(self.base + path, headers=self.h, timeout=30)
        return r.status_code, self._json(r)

    def post(self, path, body=None):
        headers = {**self.h, 'Idempotency-Key': str(uuid.uuid4())}
        r = requests.post(self.base + path, headers=headers, json=body or {}, timeout=60)
        return r.status_code, self._json(r)

    @staticmethod
    def _json(r):
        try:
            return r.json()
        except ValueError:
            return {'raw': r.text[:300]}

    def balance(self):
        code, js = self.get('/')
        return float(find(js, 'balance')) if code == 200 and find(js, 'balance') is not None else None


def poll(fn, done, timeout, every):
    end = time.time() + timeout
    while time.time() < end:
        code, js = fn()
        status = find(js, 'status')
        if done(status):
            return status, js
        time.sleep(every)
    return None, None


def run_topup(api, amount, mode):
    print(f'\n== NẠP {amount:,.0f}đ ({mode}) ==')
    before = api.balance()
    check('đọc được số dư', before is not None, f'{before}')
    code, js = api.post('/topup/', {'amount': amount})
    topup_id = find(js, 'id')
    if not check('tạo link nạp', code == 200 and topup_id, f'HTTP {code} {find(js, "detail") or find(js, "message") or ""}'):
        return None
    url = find(js, 'checkout_url')
    print(f'      checkout_url: {url}')

    if mode == 'mock':
        code, js = api.post(f'/topup/{topup_id}/mock-confirm/')
        check('giả lập thanh toán', code == 200 and find(js, 'status') == 'SUCCESS', f'HTTP {code}')
    else:
        print('      >>> Mở link trên, thanh toán bằng app ngân hàng. Đang chờ tiền vào (tối đa 10 phút)...')
        status, _ = poll(lambda: api.get(f'/topup/{topup_id}/'), lambda s: s in ('SUCCESS', 'EXPIRED', 'CANCELLED'), 600, 5)
        check('webhook payOS đã cộng ví', status == 'SUCCESS', f'trạng thái cuối: {status}')

    after = api.balance()
    check('số dư tăng đúng số tiền nạp', before is not None and after is not None and after - before == amount,
          f'{before} -> {after}')
    return after


def run_withdraw(api, amount, mode, method_id):
    print(f'\n== RÚT {amount:,.0f}đ ({mode}) ==')
    before = api.balance()
    body = {'amount': amount}
    if method_id:
        body['payment_method_id'] = method_id
    code, js = api.post('/withdraw/', body)
    wid = find(js, 'id')
    if not check('gửi lệnh rút', code == 200 and wid, f'HTTP {code} {js if code != 200 else ""}'):
        return
    status = find(js, 'status')
    print(f'      trạng thái ngay lúc gửi: {status}')
    mid = api.balance()
    if status != 'FAILED':
        check('ví bị trừ ngay', before is not None and mid is not None and before - mid == amount, f'{before} -> {mid}')

    if status == 'PROCESSING':
        wait = 600 if mode == 'real' else 90
        print(f'      đang chờ kết quả chi (tối đa {wait}s)...')
        status, js = poll(lambda: api.get(f'/withdraw/{wid}/'), lambda s: s in ('SUCCESS', 'FAILED'), wait, 5)
    check('lệnh rút ra kết quả cuối', status in ('SUCCESS', 'FAILED'), f'{status}')

    after = api.balance()
    if before is None or after is None:
        check('đọc được số dư để đối chiếu', False, f'{before} -> {after}')
    elif status == 'SUCCESS':
        check('rút thành công, ví giữ nguyên mức đã trừ', after == before - amount, f'{before} -> {after}')
    elif status == 'FAILED':
        reason = find(js, 'failure_reason')
        check('rút thất bại thì đã hoàn ví đủ', after == before, f'{before} -> {after}  ({reason})')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--token', required=True)
    ap.add_argument('--base', default='http://127.0.0.1:8000')
    ap.add_argument('--role', choices=['customer', 'worker'], default='customer')
    ap.add_argument('--mode', choices=['mock', 'real'], default='mock')
    ap.add_argument('--topup', type=float, default=200000)
    ap.add_argument('--withdraw', type=float, default=100000)
    ap.add_argument('--method-id', type=int, default=None)
    ap.add_argument('--skip-topup', action='store_true')
    ap.add_argument('--skip-withdraw', action='store_true')
    a = ap.parse_args()

    api = Api(a.base, a.token, a.role)
    if not a.skip_topup:
        run_topup(api, a.topup, a.mode)
    if not a.skip_withdraw:
        run_withdraw(api, a.withdraw, a.mode, a.method_id)

    print(f'\nKết quả: {sum(results)}/{len(results)} bước đạt')
    sys.exit(0 if all(results) else 1)


if __name__ == '__main__':
    main()