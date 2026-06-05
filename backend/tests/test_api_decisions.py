from datetime import date
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.db.database import Base
import app.db.models  # noqa
from app.db.models import Decision, Account
from app.main import create_app
from app.api.deps import get_session


def _client():
    engine = create_engine("sqlite:///:memory:", future=True,
                           connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, expire_on_commit=False, future=True)()
    s.add(Account(name="main", cash=1000000.0))
    s.add(Decision(as_of=date(2026, 5, 29), code="X", action="BUY", confidence=0.8,
                   shares=100, reasoning="md", status="PENDING", created_at=date(2026, 5, 29)))
    s.commit()
    app = create_app()
    app.dependency_overrides[get_session] = lambda: s
    return TestClient(app), s


def test_list_decisions():
    client, _ = _client()
    data = client.get("/api/decisions").json()
    assert len(data) == 1 and data[0]["action"] == "BUY" and data[0]["status"] == "PENDING"


def test_approve_executes_trade():
    client, s = _client()
    did = s.query(Decision).one().id
    r = client.post(f"/api/decisions/{did}/approve", json={"price": 1000.0})
    assert r.status_code == 200
    assert s.get(Decision, did).status == "APPROVED"
    acc = client.get("/api/account/1").json()
    assert acc["cash"] == 1000000.0 - 1000.0 * 100   # BUY executed
    assert acc["positions"][0]["code"] == "X"


def test_reject_no_trade():
    client, s = _client()
    did = s.query(Decision).one().id
    r = client.post(f"/api/decisions/{did}/reject")
    assert r.status_code == 200
    assert s.get(Decision, did).status == "REJECTED"
    assert client.get("/api/account/1").json()["cash"] == 1000000.0


_REASON = (
    "### 量价分析师\n放量突破。\n```json {\"stance\":\"bull\",\"confidence\":0.7} ```\n\n"
    "### 风控经理\n空仓观望,不接刀。\n```json {\"action\":\"HOLD\",\"confidence\":0.6,\"shares\":0} ```"
)


def test_get_decision_detail_returns_structured_roles():
    client, s = _client()
    d = Decision(as_of=date(2026, 6, 4), code="600519.SH", action="HOLD",
                 confidence=0.6, shares=0, reasoning=_REASON,
                 status="PENDING", created_at=date(2026, 6, 4))
    s.add(d); s.commit()
    body = client.get(f"/api/decisions/{d.id}").json()
    assert body["action"] == "HOLD"
    assert body["status"] == "PENDING"
    assert body["summary"].startswith("空仓观望")
    roles = body["roles"]
    assert [x["role"] for x in roles] == ["量价分析师", "风控经理"]
    assert roles[0]["stance"] == "bull" and roles[0]["stage"] == "analyst"
    assert roles[1]["stage"] == "verdict"


def test_get_decision_404():
    client, _ = _client()
    assert client.get("/api/decisions/99999").status_code == 404
