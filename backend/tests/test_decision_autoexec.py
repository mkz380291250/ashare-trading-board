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


class FakeGraphDecision:
    def __init__(self, action, shares):
        self.action = action
        self.confidence = 0.7
        self.shares = shares
        self.reasoning = "### 风控经理\n裁决"


class FakeGraph:
    def __init__(self, action, shares):
        self._a = action
        self._s = shares

    def run(self, brief):
        return FakeGraphDecision(self._a, self._s)


def _sess():
    e = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                      poolclass=StaticPool, future=True)
    Base.metadata.create_all(e)
    s = sessionmaker(bind=e, future=True)()
    s.add(Account(id=1, name="main", cash=1_000_000.0)); s.commit()
    return s


def test_autoexec_buy_sets_approved_and_buys():
    s = _sess()
    runner = DecisionRunner(s, FakeGraph("BUY", 100), broker=PaperBroker(s),
                            account_id=1, price_of=lambda c: 100.0)
    out = runner.run(date(2026, 6, 4), [build_brief("600519.SH", [100], {}, {}, None)])
    assert out[0].status == "APPROVED"
    assert s.get(Account, 1).cash == 1_000_000.0 - 100.0 * 100


def test_autoexec_hold_no_trade_but_approved():
    s = _sess()
    runner = DecisionRunner(s, FakeGraph("HOLD", 0), broker=PaperBroker(s),
                            account_id=1, price_of=lambda c: 100.0)
    out = runner.run(date(2026, 6, 4), [build_brief("X", [1], {}, {}, None)])
    assert out[0].status == "APPROVED"
    assert s.get(Account, 1).cash == 1_000_000.0


def test_no_broker_keeps_pending():
    s = _sess()
    runner = DecisionRunner(s, FakeGraph("BUY", 100))
    out = runner.run(date(2026, 6, 4), [build_brief("X", [1], {}, {}, None)])
    assert out[0].status == "PENDING"
