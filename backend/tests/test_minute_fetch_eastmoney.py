from datetime import datetime
from app.data.minute_fetch_eastmoney import EastMoneyMinuteFetcher, secid_of


class FakeLimiter:
    def __init__(self):
        self.calls = 0

    def acquire(self):
        self.calls += 1


# EastMoney klines order: time, open, close, high, low, vol, amount
_KLINES = [
    "2026-06-04 09:35,10.0,10.1,10.5,9.8,100,1000.00",
    "2026-06-04 09:40,11.0,11.2,11.5,10.8,200,2000.00",
]


def _fake_get(secid, klt, lmt):
    return {"data": {"code": "300566", "klines": list(_KLINES)}, "_secid": secid, "_klt": klt}


def test_secid_market_prefix():
    assert secid_of("600519.SH") == "1.600519"
    assert secid_of("300566.SZ") == "0.300566"
    assert secid_of("920128.BJ") == "0.920128"


def test_fetch_maps_klines_and_field_order():
    lim = FakeLimiter()
    f = EastMoneyMinuteFetcher(get_json=_fake_get, limiter=lim)
    rows = f.fetch("300566.SZ", "5min", "2026-06-04 09:00:00", "2026-06-04 15:00:00")
    assert lim.calls == 1
    assert len(rows) == 2
    r = rows[0]
    assert r["code"] == "300566.SZ" and r["freq"] == "5min"
    assert r["trade_time"] == datetime(2026, 6, 4, 9, 35)
    # EM order: open=10.0 close=10.1 high=10.5 low=9.8  (NOT tushare order)
    assert r["open"] == 10.0 and r["close"] == 10.1
    assert r["high"] == 10.5 and r["low"] == 9.8
    assert r["vol"] == 100.0 and r["amount"] == 1000.0


def test_fetch_filters_by_window():
    # start after the first bar -> only the second bar returned
    f = EastMoneyMinuteFetcher(get_json=_fake_get)
    rows = f.fetch("300566.SZ", "5min", "2026-06-04 09:38:00", "2026-06-04 15:00:00")
    assert [r["trade_time"] for r in rows] == [datetime(2026, 6, 4, 9, 40)]


def test_fetch_swallows_errors():
    def boom(*a, **k):
        raise RuntimeError("network down")
    f = EastMoneyMinuteFetcher(get_json=boom)
    assert f.fetch("300566.SZ", "5min", "a", "b") == []


def test_fetch_empty_returns_empty():
    f = EastMoneyMinuteFetcher(get_json=lambda *a, **k: {"data": None})
    assert f.fetch("300566.SZ", "5min", "a", "b") == []


def test_unknown_freq_returns_empty():
    f = EastMoneyMinuteFetcher(get_json=_fake_get)
    assert f.fetch("300566.SZ", "7min", "a", "b") == []
