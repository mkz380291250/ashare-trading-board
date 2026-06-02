from datetime import date
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.db.database import Base
import app.db.models  # noqa
from app.db.models import DiscoveryPick
from app.main import create_app
from app.api.deps import get_session


def _client():
    engine = create_engine("sqlite:///:memory:", future=True,
                           connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, expire_on_commit=False, future=True)()
    s.add(DiscoveryPick(as_of=date(2026, 5, 28), code="OLD.SH", rank=1, score=0.5, factors="{}"))
    s.add(DiscoveryPick(as_of=date(2026, 5, 29), code="NEW.SH", rank=1, score=0.9,
                        factors='{"mom_5d": 0.2}'))
    s.commit()
    app = create_app()
    app.dependency_overrides[get_session] = lambda: s
    return TestClient(app)


def test_latest_batch():
    r = _client().get("/api/discovery")
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 1 and data[0]["code"] == "NEW.SH"  # only the most recent as_of
    assert data[0]["factors"]["mom_5d"] == 0.2


def test_historical_date():
    r = _client().get("/api/discovery?date=2026-05-28")
    assert r.status_code == 200
    assert r.json()[0]["code"] == "OLD.SH"
