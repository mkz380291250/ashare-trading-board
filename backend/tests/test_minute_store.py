from datetime import datetime
from app.data.minute_store import MinuteStore


def _row(t, close):
    return {"code": "600519.SH", "freq": "1min", "trade_time": t,
            "open": close, "high": close, "low": close, "close": close,
            "vol": 100.0, "amount": 1000.0}


def test_upsert_is_idempotent(session):
    ms = MinuteStore(session)
    t = datetime(2026, 6, 4, 9, 31)
    ms.upsert("600519.SH", "1min", [_row(t, 10.0)])
    ms.upsert("600519.SH", "1min", [_row(t, 11.0)])  # same PK
    bars = ms.get_bars("600519.SH", "1min",
                       datetime(2026, 6, 4), datetime(2026, 6, 5))
    assert len(bars) == 1
    assert bars[0]["c"] == 11.0  # last write wins


def test_get_bars_sorted_and_filtered(session):
    ms = MinuteStore(session)
    ms.upsert("600519.SH", "1min", [
        _row(datetime(2026, 6, 4, 9, 32), 12.0),
        _row(datetime(2026, 6, 4, 9, 31), 11.0),
    ])
    # different freq must not leak in
    ms.upsert("600519.SH", "5min", [_row(datetime(2026, 6, 4, 9, 35), 99.0)])
    bars = ms.get_bars("600519.SH", "1min",
                       datetime(2026, 6, 4), datetime(2026, 6, 5))
    assert [b["t"] for b in bars] == [
        datetime(2026, 6, 4, 9, 31), datetime(2026, 6, 4, 9, 32)]
    assert bars[0]["o"] == 11.0 and bars[0]["v"] == 100.0


def test_last_time(session):
    ms = MinuteStore(session)
    assert ms.last_time("600519.SH", "1min") is None
    ms.upsert("600519.SH", "1min", [
        _row(datetime(2026, 6, 4, 9, 31), 11.0),
        _row(datetime(2026, 6, 4, 9, 33), 13.0),
    ])
    assert ms.last_time("600519.SH", "1min") == datetime(2026, 6, 4, 9, 33)
