from datetime import datetime
import pandas as pd
from app.data.minute_fetch import MinuteFetcher


class FakeLimiter:
    def __init__(self):
        self.calls = 0

    def acquire(self):
        self.calls += 1


class FakePro:
    def __init__(self):
        self.last_kwargs = None

    def stk_mins(self, ts_code, freq, start_date, end_date):
        self.last_kwargs = dict(ts_code=ts_code, freq=freq,
                                start_date=start_date, end_date=end_date)
        return pd.DataFrame({
            "ts_code": [ts_code, ts_code],
            "trade_time": ["2026-06-04 09:32:00", "2026-06-04 09:31:00"],
            "open": [11.0, 10.0], "high": [11.5, 10.5],
            "low": [10.8, 9.8], "close": [11.2, 10.1],
            "vol": [200.0, 100.0], "amount": [2000.0, 1000.0],
        })


def test_fetch_maps_rows_and_rate_limits():
    pro, lim = FakePro(), FakeLimiter()
    f = MinuteFetcher(pro=pro, limiter=lim)
    rows = f.fetch("600519.SH", "1min",
                   "2026-06-04 09:00:00", "2026-06-04 15:00:00")
    assert lim.calls == 1  # 走全局限频
    assert pro.last_kwargs["ts_code"] == "600519.SH"
    assert pro.last_kwargs["freq"] == "1min"
    assert len(rows) == 2
    r0 = rows[0]
    assert r0["code"] == "600519.SH" and r0["freq"] == "1min"
    assert r0["trade_time"] == datetime(2026, 6, 4, 9, 32)
    assert r0["open"] == 11.0 and r0["close"] == 11.2 and r0["amount"] == 2000.0


class BoomPro:
    def stk_mins(self, **kw):
        raise RuntimeError("抱歉,您每分钟最多访问该接口1次")


def test_fetch_swallows_errors():
    f = MinuteFetcher(pro=BoomPro(), limiter=FakeLimiter())
    assert f.fetch("600519.SH", "1min", "a", "b") == []


class EmptyPro:
    def stk_mins(self, **kw):
        return pd.DataFrame()


def test_fetch_empty_returns_empty():
    f = MinuteFetcher(pro=EmptyPro(), limiter=FakeLimiter())
    assert f.fetch("600519.SH", "1min", "a", "b") == []
