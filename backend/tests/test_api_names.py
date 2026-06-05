from datetime import date
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.db.database import Base
import app.db.models  # noqa
from app.db.models import StockName, Decision
from app.main import create_app
from app.api.deps import get_session


def _client():
    e = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                      poolclass=StaticPool, future=True)
    Base.metadata.create_all(e)
    s = sessionmaker(bind=e, future=True)()
    s.add(StockName(code="600519.SH", name="贵州茅台"))
    s.add(Decision(as_of=date(2026, 6, 4), code="600519.SH", action="HOLD",
                   confidence=0.5, shares=0, reasoning="### 风控经理\n观望",
                   status="PENDING", created_at=date(2026, 6, 4)))
    s.commit()
    app = create_app()
    app.dependency_overrides[get_session] = lambda: s
    return TestClient(app), s


def test_decisions_list_has_name():
    client, _ = _client()
    data = client.get("/api/decisions").json()
    assert data[0]["name"] == "贵州茅台"


def test_decision_detail_has_name():
    client, _ = _client()
    rows = client.get("/api/decisions").json()
    d = client.get(f"/api/decisions/{rows[0]['id']}").json()
    assert d["name"] == "贵州茅台"
