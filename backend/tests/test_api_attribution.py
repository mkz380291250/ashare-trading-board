from datetime import date
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.db.database import Base
import app.db.models  # noqa
from app.db.models import DecisionOutcome, FactorICDaily
from app.main import create_app
from app.api.deps import get_session


def _client():
    engine = create_engine("sqlite:///:memory:", future=True,
                           connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, expire_on_commit=False, future=True)()
    s.add(DecisionOutcome(decision_id=1, code="600519.SH", decided_on=date(2026, 6, 4),
                          action="BUY", entry_close=100.0, ret_t5=0.05, hit=True,
                          last_updated=date(2026, 6, 12)))
    s.add(DecisionOutcome(decision_id=2, code="000001.SZ", decided_on=date(2026, 6, 4),
                          action="BUY", entry_close=50.0, ret_t5=-0.05, hit=False,
                          last_updated=date(2026, 6, 12)))
    s.add(FactorICDaily(as_of=date(2026, 6, 4), ic=0.02, rank_ic=0.07, n=4000))
    s.add(FactorICDaily(as_of=date(2026, 6, 5), ic=0.01, rank_ic=0.03, n=4100))
    s.commit()
    app = create_app()
    app.dependency_overrides[get_session] = lambda: s
    return TestClient(app)


def test_hit_rate():
    data = _client().get("/api/attribution/hit-rate?window=30").json()
    assert data["n"] == 2 and abs(data["hit_rate"] - 0.5) < 1e-9 and data["window"] == 30


def test_forward_ic_series():
    data = _client().get("/api/attribution/forward-ic?days=60").json()
    assert len(data) == 2
    assert data[0]["as_of"] == "2026-06-04" and data[1]["rank_ic"] == 0.03
