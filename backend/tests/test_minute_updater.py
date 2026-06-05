from datetime import datetime
from app.data.minute_store import MinuteStore
from scripts.minute_updater_daemon import update_once


class FakeFetcher:
    """记录每次 fetch 的入参,按 code 返回预置行。"""
    def __init__(self, rows_by_code):
        self.rows_by_code = rows_by_code
        self.calls = []

    def fetch(self, code, freq, start, end):
        self.calls.append((code, freq, start, end))
        return self.rows_by_code.get(code, [])


def _bar(code, t, close):
    return {"code": code, "freq": "1min", "trade_time": t, "open": close,
            "high": close, "low": close, "close": close, "vol": 1.0,
            "amount": 1.0}


def test_first_round_uses_day_open_and_upserts(session):
    store = MinuteStore(session)
    t = datetime(2026, 6, 4, 9, 31)
    fetcher = FakeFetcher({"600519.SH": [_bar("600519.SH", t, 10.0)]})
    counts = update_once(fetcher, store, ["600519.SH"],
                         now=datetime(2026, 6, 4, 9, 32), freq="1min")
    assert counts == {"600519.SH": 1}
    # 库为空 -> start 应为当日 09:30
    assert fetcher.calls[0][2] == "2026-06-04 09:30:00"
    assert store.last_time("600519.SH", "1min") == t


def test_second_round_is_incremental(session):
    store = MinuteStore(session)
    store.upsert("600519.SH", "1min",
                 [_bar("600519.SH", datetime(2026, 6, 4, 9, 31), 10.0)])
    fetcher = FakeFetcher({})  # 无新行
    update_once(fetcher, store, ["600519.SH"],
                now=datetime(2026, 6, 4, 9, 40), freq="1min")
    # 增量:start 应为库内 last_time
    assert fetcher.calls[0][2] == "2026-06-04 09:31:00"


def test_multiple_codes_round_robin(session):
    store = MinuteStore(session)
    fetcher = FakeFetcher({
        "A": [_bar("A", datetime(2026, 6, 4, 9, 31), 1.0)],
        "B": [_bar("B", datetime(2026, 6, 4, 9, 31), 2.0)],
    })
    counts = update_once(fetcher, store, ["A", "B"],
                         now=datetime(2026, 6, 4, 9, 32), freq="1min")
    assert counts == {"A": 1, "B": 1}
    assert {c[0] for c in fetcher.calls} == {"A", "B"}
