from datetime import date
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.db.database import Base
import app.db.models  # noqa
from app.main import create_app
from app.api.deps import get_session
from app.backtest.store import BacktestStore


def _seeded_client():
    engine = create_engine("sqlite:///:memory:", future=True,
                           connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, expire_on_commit=False, future=True)()
    BacktestStore(s).save(signal="momentum", start=date(2026, 1, 2),
                          end=date(2026, 6, 1), params={"topk": 8},
                          strategy_metrics={"annualized_return": 0.15},
                          factor_report={"ic_mean": 0.07}, created_at=date(2026, 6, 3))
    app = create_app()
    app.dependency_overrides[get_session] = lambda: s
    return TestClient(app)


def _empty_client():
    engine = create_engine("sqlite:///:memory:", future=True,
                           connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, expire_on_commit=False, future=True)()
    app = create_app()
    app.dependency_overrides[get_session] = lambda: s
    return TestClient(app)


def test_get_latest_backtest():
    r = _seeded_client().get("/api/backtest")
    assert r.status_code == 200
    body = r.json()
    assert body["signal"] == "momentum"
    assert body["strategy_metrics"]["annualized_return"] == 0.15
    assert body["factor_report"]["ic_mean"] == 0.07


def test_get_backtest_404_when_empty():
    assert _empty_client().get("/api/backtest").status_code == 404


def test_list_recent_runs():
    r = _seeded_client().get("/api/backtest/runs?n=5")
    assert r.status_code == 200
    assert len(r.json()) == 1 and r.json()[0]["signal"] == "momentum"
