from datetime import date
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.db.database import Base
import app.db.models  # noqa
from app.main import create_app
from app.api.deps import get_session
from app.screener.pool import WatchPool


def _client():
    engine = create_engine("sqlite:///:memory:", future=True,
                           connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, expire_on_commit=False, future=True)()
    WatchPool(s).add("X.SH", "算力", date(2026, 1, 2), 10.0, {"np_yoy": 25.0})
    app = create_app()
    app.dependency_overrides[get_session] = lambda: s
    return TestClient(app)


def test_list_picks():
    r = _client().get("/api/screener/picks")
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 1
    assert data[0]["code"] == "X.SH" and data[0]["theme"] == "算力"
    assert data[0]["entry_close"] == 10.0
