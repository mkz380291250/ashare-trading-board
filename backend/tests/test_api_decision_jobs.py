from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.db.database import Base
import app.db.models  # noqa
from app.db.models import DecisionJob
from app.main import create_app
from app.api.deps import get_session
import app.api.routes_decisions as rd


def _client(monkeypatch):
    e = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                      poolclass=StaticPool, future=True)
    Base.metadata.create_all(e)
    s = sessionmaker(bind=e, future=True)()
    app = create_app()
    app.dependency_overrides[get_session] = lambda: s
    monkeypatch.setattr(rd, "_spawn_decision_worker", lambda job_id, code: None)
    return TestClient(app), s


def test_run_creates_pending_job_and_normalizes(monkeypatch):
    client, s = _client(monkeypatch)
    r = client.post("/api/decisions/run", json={"code": "600519"})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "PENDING"
    assert body["code"] == "600519.SH"
    assert s.get(DecisionJob, body["id"]) is not None


def test_jobs_lists(monkeypatch):
    client, s = _client(monkeypatch)
    client.post("/api/decisions/run", json={"code": "600519"})
    jobs = client.get("/api/decisions/jobs").json()
    assert len(jobs) == 1 and jobs[0]["code"] == "600519.SH"
