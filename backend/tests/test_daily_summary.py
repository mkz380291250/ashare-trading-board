from datetime import date
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.db.database import Base
import app.db.models  # noqa
from app.db.models import Account, Trade, EquitySnapshot
from app.reporting.daily_summary import build_daily_summary


def _sess():
    e = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                      poolclass=StaticPool, future=True)
    Base.metadata.create_all(e)
    s = sessionmaker(bind=e, future=True)()
    s.add(Account(id=1, name="main", cash=500_000.0)); s.commit()
    return s


def test_summary_lists_today_trades_and_drawdown():
    s = _sess()
    d = date(2026, 6, 4)
    s.add(Trade(account_id=1, code="600519.SH", side="BUY", price=100, shares=100, traded_at=d))
    s.add(EquitySnapshot(account_id=1, as_of=date(2026, 6, 1), cash=0, market_value=0, total=1_200_000.0))
    s.add(EquitySnapshot(account_id=1, as_of=d, cash=500_000.0, market_value=520_000.0, total=1_020_000.0))
    s.commit()
    text = build_daily_summary(s, d, account_id=1)
    assert "600519.SH" in text
    assert "买" in text
    # 峰值 1_200_000 → 当前 1_020_000,回撤 -15%
    assert "-15" in text
    assert "|" not in text and "---" not in text       # 不含 markdown 表格


def test_summary_handles_no_snapshot():
    s = _sess()
    text = build_daily_summary(s, date(2026, 6, 4), account_id=1)
    assert "N/A" in text
