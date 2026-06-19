from __future__ import annotations

import time
from collections import deque


class RateLimiter:
    def __init__(
        self,
        *,
        api_per_minute: int = 100,
        api_per_day: int = 5000,
        order_actions_per_second: int = 10,
    ):
        self.api_per_minute = api_per_minute
        self.api_per_day = api_per_day
        self.order_actions_per_second = order_actions_per_second
        self._api_minute: deque[float] = deque()
        self._api_day: deque[float] = deque()
        self._orders_second: deque[float] = deque()

    def can_call_api(self) -> tuple[bool, str]:
        now = time.time()
        self._trim(now)
        if len(self._api_minute) >= self.api_per_minute:
            return False, "Breeze API minute limit would be exceeded."
        if len(self._api_day) >= self.api_per_day:
            return False, "Breeze API daily limit would be exceeded."
        return True, "Breeze API rate limit is available."

    def can_send_order_action(self) -> tuple[bool, str]:
        now = time.time()
        self._trim(now)
        if len(self._orders_second) >= self.order_actions_per_second:
            return False, "Breeze order action per-second limit would be exceeded."
        return True, "Breeze order action rate limit is available."

    def record_api_call(self) -> None:
        ok, reason = self.can_call_api()
        if not ok:
            raise RateLimitError(reason)
        now = time.time()
        self._api_minute.append(now)
        self._api_day.append(now)

    def record_order_action(self) -> None:
        ok, reason = self.can_send_order_action()
        if not ok:
            raise RateLimitError(reason)
        self._orders_second.append(time.time())

    def _trim(self, now: float) -> None:
        minute_cutoff = now - 60
        day_cutoff = now - 86400
        second_cutoff = now - 1

        while self._api_minute and self._api_minute[0] < minute_cutoff:
            self._api_minute.popleft()
        while self._api_day and self._api_day[0] < day_cutoff:
            self._api_day.popleft()
        while self._orders_second and self._orders_second[0] < second_cutoff:
            self._orders_second.popleft()


class RateLimitError(RuntimeError):
    pass
