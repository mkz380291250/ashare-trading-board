from datetime import date
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.db.database import Base
import app.db.models  # noqa
from app.db.models import Account, EquitySnapshot
from app.main import create_app
from app.api.deps import get_session


def _client():
    engine = create_engine("sqlite:///:memory:", future=True,
                           connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, expire_on_commit=False, future=True)()
    s.add(Account(id=1, name="main", cash=0.0))
    for d, t in [(date(2026, 6, 1), 100.0), (date(2026, 6, 2), 120.0), (date(2026, 6, 3), 102.0)]:
        s.add(EquitySnapshot(account_id=1, as_of=d, cash=0, market_value=0, total=t))
    s.commit()
    app = create_app()
    app.dependency_overrides[get_session] = lambda: s
    return TestClient(app)


def test_equity_has_drawdown():
    data = _client().get("/api/equity/1").json()
    assert len(data) == 3
    assert data[0]["drawdown"] == 0.0              # 首点峰值=自身
    assert abs(data[2]["drawdown"] - (102/120 - 1)) < 1e-9   # 峰值120
