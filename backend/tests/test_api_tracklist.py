from datetime import date
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.db.database import Base
import app.db.models  # noqa: F401
from app.api import deps
from app.db.models import DailyQuote
from app.main import create_app


@pytest.fixture
def client():
    engine = create_engine("sqlite:///:memory:", future=True,
                           connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    s = factory()
    s.add(DailyQuote(code="300975", trade_date=date(2026, 6, 3),
                     open=43.0, high=44.0, low=42.5, close=43.41, vol=1000.0))
    s.commit(); s.close()

    def _override():
        s = factory()
        try:
            yield s
        finally:
            s.close()
    app = create_app()
    app.dependency_overrides[deps.get_session] = _override
    return TestClient(app)


def test_post_parses_and_adds(client):
    r = client.post("/api/track", json={"text": "商络电子 43.41\n融 300975"})
    assert r.status_code == 200
    body = r.json()
    assert body["added"][0]["code"] == "300975"
    assert body["added"][0]["entry_close"] == 43.41


def test_get_lists(client):
    client.post("/api/track", json={"text": "商络电子\n300975"})
    rows = client.get("/api/track").json()
    assert any(x["code"] == "300975" for x in rows)


def test_delete(client):
    client.post("/api/track", json={"text": "商络电子\n300975"})
    assert client.delete("/api/track/300975/2026-06-03").status_code == 200
    assert client.get("/api/track").json() == []
