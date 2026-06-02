from datetime import date
from app.db.models import DiscoveryPick


def test_discovery_pick_roundtrip(session):
    p = DiscoveryPick(as_of=date(2026, 5, 29), code="600519.SH", rank=1,
                      score=0.95, factors='{"mom_5d": 0.1}')
    session.add(p); session.commit()
    got = session.query(DiscoveryPick).one()
    assert got.code == "600519.SH" and got.rank == 1
    assert got.score == 0.95 and got.as_of == date(2026, 5, 29)
