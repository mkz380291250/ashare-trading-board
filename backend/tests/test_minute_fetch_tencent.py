from datetime import datetime
from app.data.minute_fetch_tencent import TencentMinuteFetcher, tencent_symbol


class FakeLimiter:
    def __init__(self):
        self.calls = 0

    def acquire(self):
        self.calls += 1


# Tencent mkline row order: time(YYYYMMDDHHMM), open, close, high, low, vol, {}, ...
_ROWS = [
    ["202606040935", "10.0", "10.1", "10.5", "9.8", "100", {}, "0.45"],
    ["202606040940", "11.0", "11.2", "11.5", "10.8", "200", {}, "0.72"],
]


def _fake_get(symbol, freq_key, lmt):
    return {"data": {symbol: {freq_key: list(_ROWS), "qt": {}}},
            "_symbol": symbol, "_freq": freq_key}


def test_tencent_symbol_prefix():
    assert tencent_symbol("600519.SH") == "sh600519"
    assert tencent_symbol("300566.SZ") == "sz300566"
    assert tencent_symbol("920128.BJ") == "bj920128"


def test_fetch_maps_rows_and_field_order():
    lim = FakeLimiter()
    f = TencentMinuteFetcher(get_json=_fake_get, limiter=lim)
    rows = f.fetch("300566.SZ", "5min", "2026-06-04 09:00:00", "2026-06-04 15:00:00")
    assert lim.calls == 1
    assert len(rows) == 2
    r = rows[0]
    assert r["code"] == "300566.SZ" and r["freq"] == "5min"
    assert r["trade_time"] == datetime(2026, 6, 4, 9, 35)
    # Tencent order: open=10.0 close=10.1 high=10.5 low=9.8
    assert r["open"] == 10.0 and r["close"] == 10.1
    assert r["high"] == 10.5 and r["low"] == 9.8
    assert r["vol"] == 100.0


def test_fetch_filters_by_window():
    f = TencentMinuteFetcher(get_json=_fake_get)
    rows = f.fetch("300566.SZ", "5min", "2026-06-04 09:38:00", "2026-06-04 15:00:00")
    assert [r["trade_time"] for r in rows] == [datetime(2026, 6, 4, 9, 40)]


def test_fetch_swallows_errors():
    def boom(*a, **k):
        raise RuntimeError("network down")
    f = TencentMinuteFetcher(get_json=boom)
    assert f.fetch("300566.SZ", "5min", "a", "b") == []


def test_fetch_empty_returns_empty():
    f = TencentMinuteFetcher(get_json=lambda *a, **k: {"data": {"sz300566": {}}})
    assert f.fetch("300566.SZ", "5min", "a", "b") == []


def test_unknown_freq_returns_empty():
    f = TencentMinuteFetcher(get_json=_fake_get)
    assert f.fetch("300566.SZ", "7min", "a", "b") == []
