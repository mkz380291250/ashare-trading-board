from app.data.rate_limiter import RateLimiter


class FakeClock:
    def __init__(self): self.t = 0.0
    def now(self): return self.t
    def sleep(self, dt): self.t += dt  # sleeping advances time


def test_never_exceeds_max_in_window():
    clk = FakeClock()
    rl = RateLimiter(max_calls=100, period_s=60, now=clk.now, sleep=clk.sleep)
    times = []
    for _ in range(250):
        rl.acquire()
        times.append(clk.now())
    for i, t in enumerate(times):
        window = [u for u in times[: i + 1] if u > t - 60]
        assert len(window) <= 100


def test_first_100_are_immediate():
    clk = FakeClock()
    rl = RateLimiter(max_calls=100, period_s=60, now=clk.now, sleep=clk.sleep)
    for _ in range(100):
        rl.acquire()
    assert clk.now() == 0.0          # no sleep needed for first 100
    rl.acquire()                      # 101st must wait
    assert clk.now() > 0.0
