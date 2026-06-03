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


def test_list_research_returns_latest_per_code():
    from datetime import date as _d
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool
    from app.db.database import Base
    import app.db.models  # noqa
    from app.main import create_app
    from app.api.deps import get_session
    from app.research.store import ResearchStore, AnalyzedNote
    from fastapi.testclient import TestClient
    engine = create_engine("sqlite:///:memory:", future=True,
                           connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, expire_on_commit=False, future=True)()
    ResearchStore(s).upsert("600519.SH", _d(2026, 6, 3), AnalyzedNote(0.5, "买入", "稳"), "x")
    app = create_app()
    app.dependency_overrides[get_session] = lambda: s
    r = TestClient(app).get("/api/research")
    assert r.status_code == 200
    assert r.json()[0]["code"] == "600519.SH" and r.json()[0]["sentiment"] == 0.5
