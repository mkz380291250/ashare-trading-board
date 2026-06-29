from datetime import date, datetime
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.db.database import Base
import app.db.models  # noqa
from app.db.models import SchedulerRun
from app.main import create_app
from app.api.deps import get_session


def _client(seed=True):
    engine = create_engine("sqlite:///:memory:", future=True,
                           connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, expire_on_commit=False, future=True)()
    if seed:
        s.add(SchedulerRun(as_of=date(2026, 6, 27), started_at=datetime(2026, 6, 27, 22, 0, 0),
                           finished_at=datetime(2026, 6, 27, 22, 8, 0), ok=True,
                           detail='[{"step":"quotes","ok":true,"error":""}]'))
        s.add(SchedulerRun(as_of=date(2026, 6, 28), started_at=datetime(2026, 6, 28, 22, 0, 0),
                           finished_at=datetime(2026, 6, 28, 22, 6, 0), ok=False,
                           detail='[{"step":"quotes","ok":true,"error":""},'
                                  '{"step":"qlib","ok":false,"error":"boom"}]'))
        s.commit()
    app = create_app()
    app.dependency_overrides[get_session] = lambda: s
    return TestClient(app)


def test_last_run_returns_latest_with_failed_steps():
    data = _client().get("/api/health/last-run").json()
    assert data["as_of"] == "2026-06-28"        # 最新一次
    assert data["ok"] is False
    assert data["failed_steps"] == ["qlib"]
    assert data["started_at"].startswith("2026-06-28T22:00")
    assert data["finished_at"].startswith("2026-06-28T22:06")


def test_last_run_null_when_empty():
    assert _client(seed=False).get("/api/health/last-run").json() is None
