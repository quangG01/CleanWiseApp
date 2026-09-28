from rest_framework.throttling import ScopedRateThrottle


class WriteScopedThrottleMixin:
    """Chỉ áp scope riêng cho POST/PUT/PATCH/DELETE, GET dùng mức toàn cục."""
    write_throttle_scope = None

    def get_throttles(self):
        throttles = super().get_throttles()
        if self.write_throttle_scope and self.request.method in ('POST', 'PUT', 'PATCH', 'DELETE'):
            self.throttle_scope = self.write_throttle_scope
            throttles.append(ScopedRateThrottle())
        return throttles