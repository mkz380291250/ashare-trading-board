from datetime import date
from app.db.models import TrackEntry


def test_track_entry_persists(session):
    e = TrackEntry(code="300975", added_on=date(2026, 6, 3), name="商络电子",
                   entry_close=43.41)
    session.add(e); session.commit()
    got = session.get(TrackEntry, ("300975", date(2026, 6, 3)))
    assert got.name == "商络电子"
    assert got.entry_close == 43.41
    assert got.ret_t1 is None and got.max_drawdown is None
