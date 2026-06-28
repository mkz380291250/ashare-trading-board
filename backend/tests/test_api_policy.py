from datetime import date
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.db.database import Base
import app.db.models  # noqa
from app.db.models import PolicyAction
from app.main import create_app
from app.api.deps import get_session


def _client():
    engine = create_engine("sqlite:///:memory:", future=True,
                           connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, expire_on_commit=False, future=True)()
    s.add(PolicyAction(kind="RISK_OFF", as_of=date(2026, 6, 27), trigger='{"reason":"回撤"}',
                       detail="停买", status="AUTO", created_at=date(2026, 6, 27)))
    s.add(PolicyAction(kind="REMINE", as_of=date(2026, 6, 28), trigger='{"rolling_rank_ic":0.01}',
                       detail="重挖", status="AUTO", created_at=date(2026, 6, 28)))
    s.commit()
    app = create_app()
    app.dependency_overrides[get_session] = lambda: s
    return TestClient(app)


def test_policy_actions_desc():
    data = _client().get("/api/policy/actions?limit=50").json()
    assert len(data) == 2
    assert data[0]["kind"] == "REMINE"          # 最新在前
    assert data[1]["kind"] == "RISK_OFF" and data[1]["status"] == "AUTO"
