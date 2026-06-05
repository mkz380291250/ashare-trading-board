from datetime import date
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.db.database import Base
import app.db.models  # noqa
from app.db.models import Account, Position, Trade, StockName, DailyQuote
from app.main import create_app
from app.api.deps import get_session


def _client():
    e = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                      poolclass=StaticPool, future=True)
    Base.metadata.create_all(e)
    s = sessionmaker(bind=e, future=True)()
    s.add(Account(id=1, name="main", cash=100000.0))
    s.add(Position(account_id=1, code="600519.SH", shares=100, cost=1500.0))
    s.add(StockName(code="600519.SH", name="贵州茅台"))
    s.add(Trade(account_id=1, code="600519.SH", side="BUY", price=1500.0,
                shares=100, traded_at=date(2026, 6, 1)))
    # DailyQuote NOT NULL columns: code, trade_date, open, high, low, close, vol
    # adj_factor has default=1.0 but we set it explicitly; amount/pre_close are nullable
    s.add(DailyQuote(code="600519.SH", trade_date=date(2026, 6, 4), close=1650.0,
                     open=1600.0, high=1660.0, low=1590.0, vol=50000.0,
                     adj_factor=1.0))
    s.commit()
    app = create_app()
    app.dependency_overrides[get_session] = lambda: s
    return TestClient(app), s


def test_account_position_has_pnl_and_name_and_buydate():
    client, _ = _client()
    p = client.get("/api/account/1").json()["positions"][0]
    assert p["name"] == "贵州茅台"
    assert p["buy_date"] == "2026-06-01"
    assert p["last_close"] == 1650.0
    assert p["market_value"] == 1650.0 * 100
    assert round(p["pnl"], 2) == round((1650.0 - 1500.0) * 100, 2)
    assert round(p["pnl_pct"], 4) == round(1650.0 / 1500.0 - 1, 4)
