from datetime import datetime, date
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.db.database import Base
import app.db.models  # noqa: F401
from app.api import deps
from app.db.models import MinuteQuote, StockName
from app.main import create_app


@pytest.fixture
def client():
    engine = create_engine("sqlite:///:memory:", future=True,
                           connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    s = factory()
    s.add(StockName(code="600519.SH", name="贵州茅台"))
    for i, c in enumerate([10.0, 11.0]):
        s.add(MinuteQuote(code="600519.SH", freq="1min",
                          trade_time=datetime(2026, 6, 4, 9, 31 + i),
                          open=c, high=c, low=c, close=c, vol=1.0, amount=1.0))
    # 别的周期不应混入 1min 查询
    s.add(MinuteQuote(code="600519.SH", freq="5min",
                      trade_time=datetime(2026, 6, 4, 9, 35),
                      open=99.0, high=99.0, low=99.0, close=99.0, vol=1.0))
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


def test_kline_reads_db_only(client):
    r = client.get("/api/kline/600519.SH?freq=1min&days=30")
    assert r.status_code == 200
    body = r.json()
    assert body["code"] == "600519.SH"
    assert body["name"] == "贵州茅台"
    assert body["freq"] == "1min"
    assert len(body["bars"]) == 2  # 5min 不混入
    assert body["bars"][0]["c"] == 10.0
    assert body["last_time"] is not None


def test_kline_freq_passthrough(client):
    r = client.get("/api/kline/600519.SH?freq=5min&days=30")
    body = r.json()
    assert body["freq"] == "5min"
    assert len(body["bars"]) == 1
    assert body["bars"][0]["c"] == 99.0


def test_kline_empty_when_no_data(client):
    r = client.get("/api/kline/000001.SZ?freq=1min")
    assert r.status_code == 200
    body = r.json()
    assert body["bars"] == []
    assert body["last_time"] is None
