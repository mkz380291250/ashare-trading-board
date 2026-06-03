from datetime import date
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.db.database import Base
import app.db.models  # noqa
from app.main import create_app
from app.api.deps import get_session
from app.research.store import ResearchStore, AnalyzedNote


def _client():
    engine = create_engine("sqlite:///:memory:", future=True,
                           connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, expire_on_commit=False, future=True)()
    ResearchStore(s).upsert("600519.SH", date(2026, 6, 3),
                            AnalyzedNote(0.5, "买入", "稳"), "tushare")
    app = create_app()
    app.dependency_overrides[get_session] = lambda: s
    return TestClient(app)


def test_get_research_returns_latest():
    r = _client().get("/api/research/600519.SH")
    assert r.status_code == 200
    assert r.json()["sentiment"] == 0.5 and r.json()["summary"] == "稳"


def test_get_research_404_when_absent():
    r = _client().get("/api/research/999999.SZ")
    assert r.status_code == 404
