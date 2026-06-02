from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.db.database import Base
import app.db.models  # noqa
from app.db.models import Account
from app.main import create_app
from app.api.deps import get_session


def _client_with_db():
    # in-memory sqlite shared across TestClient's threadpool requires StaticPool
    # + check_same_thread=False, otherwise sqlite raises a cross-thread error.
    engine = create_engine(
        "sqlite:///:memory:", future=True,
        connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    s = factory()
    s.add(Account(name="main", cash=100000.0)); s.commit()
    app = create_app()
    app.dependency_overrides[get_session] = lambda: s
    return TestClient(app), s


def test_buy_then_account_reflects_position():
    client, _ = _client_with_db()
    r = client.post("/api/trade", json={"account_id": 1, "code": "X", "side": "BUY",
                                        "price": 10.0, "shares": 100, "on": "2026-05-29"})
    assert r.status_code == 200
    acc = client.get("/api/account/1").json()
    assert acc["cash"] == 99000.0
    assert acc["positions"][0]["code"] == "X"
    assert acc["positions"][0]["shares"] == 100
