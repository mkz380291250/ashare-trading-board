from datetime import date
from app.data.source import DailyBar
from app.screener.pool import WatchPool


def _bars(start_close):
    # 12 ascending trading days from 2026-01-02, close grows by 1 each day
    out = []
    for i in range(12):
        d = date(2026, 1, 2 + i)
        c = start_close + i
        out.append(DailyBar("X", d, c, c, c, c, 1000, 1.0))
    return out


def test_add_is_idempotent(session):
    wp = WatchPool(session)
    wp.add(code="X", theme="算力", on=date(2026, 1, 2), entry_close=10.0, trigger={"a": 1})
    wp.add(code="X", theme="算力", on=date(2026, 1, 2), entry_close=11.0, trigger={"a": 2})
    picks = wp.list()
    assert len(picks) == 1
    assert picks[0].entry_close == 10.0   # first selection preserved


def test_update_forward_returns(session):
    wp = WatchPool(session)
    wp.add(code="X", theme="算力", on=date(2026, 1, 2), entry_close=10.0, trigger={})
    # bars: entry day close=10 (index0); +1 each day -> T+1=11,T+3=13,T+5=15,T+10=20
    wp.update_forward_returns("X", date(2026, 1, 2), _bars(10.0))
    p = wp.list()[0]
    assert abs(p.ret_t1 - 0.1) < 1e-9    # 11/10 - 1
    assert abs(p.ret_t3 - 0.3) < 1e-9
    assert abs(p.ret_t5 - 0.5) < 1e-9
    assert abs(p.ret_t10 - 1.0) < 1e-9
