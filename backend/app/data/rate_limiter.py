import time
from collections import deque


class RateLimiter:
    """Allow at most `max_calls` within any rolling `period_s` window."""

    def __init__(self, max_calls: int, period_s: float = 60.0,
                 now=time.monotonic, sleep=time.sleep):
        self.max_calls = max_calls
        self.period_s = period_s
        self._now = now
        self._sleep = sleep
        self._calls: deque[float] = deque()

    def acquire(self) -> None:
        t = self._now()
        while self._calls and self._calls[0] <= t - self.period_s:
            self._calls.popleft()
        if len(self._calls) >= self.max_calls:
            wait = self._calls[0] + self.period_s - t
            if wait > 0:
                self._sleep(wait)
            t = self._now()
            while self._calls and self._calls[0] <= t - self.period_s:
                self._calls.popleft()
        self._calls.append(self._now())
