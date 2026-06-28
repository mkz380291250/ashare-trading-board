# backend/tests/test_attribution_integration.py
import pytest
from datetime import date
from app.db.database import make_engine, make_session_factory
import app.db.models  # noqa
from app.data.quote_store import QuoteStore
from app.attribution.outcomes import backfill_outcomes
from app.attribution.forward_ic import backfill_factor_ic

pytestmark = pytest.mark.integration


def test_attribution_backfill_runs_on_real_db():
    session = make_session_factory(make_engine())()
    store = QuoteStore(session)
    as_of = store.trading_dates(date.today(), 1)[0]
    # 真实库上回填不应抛错;行数 >= 0
    n_oc = backfill_outcomes(session, store, as_of)
    n_ic = backfill_factor_ic(session, store, as_of)
    assert n_oc >= 0 and n_ic >= 0
