# backend/tests/test_policy_integration.py
import pytest
from datetime import date
from app.db.database import make_engine, make_session_factory
import app.db.models  # noqa
from app.data.quote_store import QuoteStore
from app.policy.rules import factor_decayed, is_risk_off, weak_holdings

pytestmark = pytest.mark.integration


def test_policy_rules_run_on_real_db():
    session = make_session_factory(make_engine())()
    store = QuoteStore(session)
    as_of = store.trading_dates(date.today(), 1)[0]
    # 真实库上三个检测器都不应抛错
    dec = factor_decayed(session, as_of)
    off, _ = is_risk_off(session, as_of)
    weak = weak_holdings(session, set(), as_of)
    assert isinstance(dec, bool) and isinstance(off, bool) and weak == []
