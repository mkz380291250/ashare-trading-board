# backend/tests/test_daily_pipeline.py
from datetime import date
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.db.database import Base
import app.db.models  # noqa
from app.db.models import Account, Decision
from app.decision.brief import build_brief
from app.trading.broker import PaperBroker
from app.decision.daily_pipeline import run_daily_decisions, today_decided_codes


class _Dec:
    def __init__(self, action, shares=100, confidence=0.8):
        self.action = action; self.shares = shares
        self.confidence = confidence; self.reasoning = "### 风控经理\n裁决"


class _Graph:
    """按代码尾号决定动作:默认全 BUY。"""
    def __init__(self, mapping=None): self._m = mapping or {}
    def run(self, brief):
        return self._m.get(brief.code, _Dec("BUY"))


def _sess():
    e = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                      poolclass=StaticPool, future=True)
    Base.metadata.create_all(e)
    s = sessionmaker(bind=e, future=True)()
    s.add(Account(id=1, name="main", cash=1_000_000.0)); s.commit()
    return s


def _bb(codes):
    return [build_brief(c, [100.0, 101.0], {}, {}, None) for c in codes]


def _ranking(n):
    return [(f"c{i}", float(n - i)) for i in range(n)]


def test_pipeline_debates_bounded_and_executes_buys():
    s = _sess()
    summary = run_daily_decisions(
        s, date(2026, 6, 4), _ranking(100), held_codes=set(),
        graph=_Graph(), brief_builder=_bb, broker=PaperBroker(s),
        price_of=lambda c: 100.0, target=3, quality_pctl=0.30, min_confidence=0.6,
        max_debate=32)
    assert summary["n_debated"] == 3              # 空仓填3个空位
    assert summary["n_buy"] == 3
    assert s.query(Decision).count() == 3
    assert s.get(Account, 1).cash == 1_000_000.0 - 3 * 100.0 * 100


def test_pipeline_idempotent_skips_already_decided():
    s = _sess()
    kw = dict(graph=_Graph(), brief_builder=_bb, broker=PaperBroker(s),
              price_of=lambda c: 100.0, target=3, quality_pctl=0.30,
              min_confidence=0.6, max_debate=32)
    run_daily_decisions(s, date(2026, 6, 4), _ranking(100), set(), **kw)
    cash_after_first = s.get(Account, 1).cash
    run_daily_decisions(s, date(2026, 6, 4), _ranking(100), set(), **kw)
    assert s.query(Decision).count() == 3          # 不新增决策
    assert s.get(Account, 1).cash == cash_after_first   # 不重复下单


def test_today_decided_codes():
    s = _sess()
    s.add(Decision(as_of=date(2026, 6, 4), code="600519.SH", action="BUY",
                   confidence=0.8, shares=100, reasoning="", status="APPROVED",
                   created_at=date(2026, 6, 4)))
    s.commit()
    assert today_decided_codes(s, date(2026, 6, 4)) == {"600519.SH"}
    assert today_decided_codes(s, date(2026, 6, 5)) == set()
