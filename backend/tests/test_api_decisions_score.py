from datetime import date
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.db.database import Base
import app.db.models  # noqa
from app.db.models import Account, Decision, DiscoveryPick
from app.main import create_app
from app.api.deps import get_session


def _client():
    engine = create_engine("sqlite:///:memory:", future=True,
                           connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, expire_on_commit=False, future=True)()
    s.add(Account(name="main", cash=0.0))
    d = date(2026, 6, 4)
    s.add(Decision(as_of=d, code="600519.SH", action="BUY", confidence=0.8, shares=100,
                   reasoning="x", status="APPROVED", created_at=d))
    s.add(DiscoveryPick(as_of=d, code="600519.SH", rank=1, score=0.95, factors="{}"))
    s.commit()
    app = create_app()
    app.dependency_overrides[get_session] = lambda: s
    return TestClient(app)


def test_decisions_include_score():
    data = _client().get("/api/decisions").json()
    assert data[0]["score"] == 0.95 and data[0]["confidence"] == 0.8
