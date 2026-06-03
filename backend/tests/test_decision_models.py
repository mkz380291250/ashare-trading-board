from datetime import date
from app.db.models import Decision


def test_decision_roundtrip(session):
    d = Decision(as_of=date(2026, 5, 29), code="600519.SH", action="BUY",
                 confidence=0.7, shares=100, reasoning="**bull** wins",
                 status="PENDING", created_at=date(2026, 5, 29))
    session.add(d); session.commit()
    got = session.query(Decision).one()
    assert got.code == "600519.SH" and got.action == "BUY"
    assert got.status == "PENDING" and got.shares == 100
