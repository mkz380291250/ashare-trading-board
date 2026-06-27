# backend/tests/test_decision_runner_confidence.py
from datetime import date
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.db.database import Base
import app.db.models  # noqa
from app.db.models import Account
from app.decision.runner import DecisionRunner
from app.decision.brief import build_brief
from app.trading.broker import PaperBroker


class _Dec:
    def __init__(self, action, shares, confidence):
        self.action = action; self.shares = shares
        self.confidence = confidence; self.reasoning = "### 风控经理\n裁决"


class _Graph:
    def __init__(self, dec): self._d = dec
    def run(self, brief): return self._d


def _sess():
    e = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                      poolclass=StaticPool, future=True)
    Base.metadata.create_all(e)
    s = sessionmaker(bind=e, future=True)()
    s.add(Account(id=1, name="main", cash=1_000_000.0)); s.commit()
    return s


def test_below_threshold_records_lowconf_no_trade():
    s = _sess()
    runner = DecisionRunner(s, _Graph(_Dec("BUY", 100, 0.5)), broker=PaperBroker(s),
                            account_id=1, price_of=lambda c: 100.0, min_confidence=0.6)
    out = runner.run(date(2026, 6, 4), [build_brief("600519.SH", [100], {}, {}, None)])
    assert out[0].status == "LOW_CONF"
    assert s.get(Account, 1).cash == 1_000_000.0          # 没扣钱=没下单


def test_at_or_above_threshold_executes():
    s = _sess()
    runner = DecisionRunner(s, _Graph(_Dec("BUY", 100, 0.6)), broker=PaperBroker(s),
                            account_id=1, price_of=lambda c: 100.0, min_confidence=0.6)
    out = runner.run(date(2026, 6, 4), [build_brief("600519.SH", [100], {}, {}, None)])
    assert out[0].status == "APPROVED"
    assert s.get(Account, 1).cash == 1_000_000.0 - 100.0 * 100
