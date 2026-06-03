from datetime import date
from app.db.models import TrackEntry
from app.data.source import DailyBar
from app.screener.tracklist import Tracker


def test_track_entry_persists(session):
    e = TrackEntry(code="300975", added_on=date(2026, 6, 3), name="商络电子",
                   entry_close=43.41)
    session.add(e); session.commit()
    got = session.get(TrackEntry, ("300975", date(2026, 6, 3)))
    assert got.name == "商络电子"
    assert got.entry_close == 43.41
    assert got.ret_t1 is None and got.max_drawdown is None


def _bars(start_close, n=12):
    out = []
    for i in range(n):
        d = date(2026, 6, 3 + i)
        c = start_close + i
        out.append(DailyBar("X", d, c, c, c, c, 1000, 1.0))
    return out


def test_add_is_idempotent(session):
    t = Tracker(session)
    t.add([("X", "测试")], on=date(2026, 6, 3), closes={"X": 10.0})
    t.add([("X", "改名")], on=date(2026, 6, 3), closes={"X": 99.0})
    rows = t.list()
    assert len(rows) == 1
    assert rows[0].entry_close == 10.0 and rows[0].name == "测试"


def test_add_skips_codes_without_close(session):
    t = Tracker(session)
    added = t.add([("X", "有"), ("Y", "无")], on=date(2026, 6, 3),
                  closes={"X": 10.0})
    assert [e.code for e in added] == ["X"]


def test_update_metrics(session):
    t = Tracker(session)
    t.add([("X", "测试")], on=date(2026, 6, 3), closes={"X": 10.0})
    t.update_metrics("X", date(2026, 6, 3), _bars(10.0))
    e = t.list()[0]
    assert abs(e.ret_t1 - 0.1) < 1e-9
    assert abs(e.ret_t3 - 0.3) < 1e-9
    assert abs(e.ret_t5 - 0.5) < 1e-9
    assert abs(e.ret_t10 - 1.0) < 1e-9
    assert abs(e.last_close - 21.0) < 1e-9
    assert abs(e.ret_since - 1.1) < 1e-9
    assert abs(e.max_gain - 1.1) < 1e-9
    assert e.last_updated == date(2026, 6, 14)


def test_update_metrics_drawdown(session):
    t = Tracker(session)
    t.add([("X", "测试")], on=date(2026, 6, 3), closes={"X": 10.0})
    bars = [DailyBar("X", date(2026, 6, 3), 10, 10, 10, 10, 1, 1.0),
            DailyBar("X", date(2026, 6, 4), 12, 12, 12, 12, 1, 1.0),
            DailyBar("X", date(2026, 6, 5), 9, 9, 9, 9, 1, 1.0)]
    t.update_metrics("X", date(2026, 6, 3), bars)
    e = t.list()[0]
    assert abs(e.max_gain - 0.2) < 1e-9
    assert abs(e.max_drawdown - (-0.25)) < 1e-9


def test_remove(session):
    t = Tracker(session)
    t.add([("X", "测试")], on=date(2026, 6, 3), closes={"X": 10.0})
    t.remove("X", date(2026, 6, 3))
    assert t.list() == []
