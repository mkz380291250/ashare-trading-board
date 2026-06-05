from datetime import date
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.db.database import Base
import app.db.models  # noqa
from app.db.models import Account, DecisionJob, DailyQuote
from app.data.quote_store import QuoteStore
from app.research.store import ResearchStore
from scripts.run_one_decision import run_one


class FakeDec:
    action = "HOLD"; confidence = 0.5; shares = 0; reasoning = "### 风控经理\n观望"


class FakeGraph:
    def run(self, brief):
        return FakeDec()


def _sess():
    e = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                      poolclass=StaticPool, future=True)
    Base.metadata.create_all(e)
    s = sessionmaker(bind=e, future=True)()
    s.add(Account(id=1, name="main", cash=100000.0))
    s.add(DailyQuote(
        code="600519.SH", trade_date=date(2026, 6, 4),
        open=1640.0, high=1660.0, low=1630.0, close=1650.0,
        vol=50000.0, amount=82500000.0, adj_factor=1.0,
    ))
    j = DecisionJob(code="600519.SH", status="PENDING", created_at=date(2026, 6, 4))
    s.add(j); s.commit()
    return s, j.id


def test_run_one_marks_done_and_creates_decision():
    s, jid = _sess()
    run_one(s, jid, "600519.SH", FakeGraph(), QuoteStore(s), ResearchStore(s))
    job = s.get(DecisionJob, jid)
    assert job.status == "DONE"
    assert job.decision_id is not None
