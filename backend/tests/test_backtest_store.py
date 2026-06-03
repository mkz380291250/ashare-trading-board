from datetime import date
from app.backtest.store import BacktestStore


def test_save_and_latest(session):
    st = BacktestStore(session)
    st.save(signal="momentum", start=date(2026, 1, 2), end=date(2026, 6, 1),
            params={"topk": 8}, strategy_metrics={"annualized_return": 0.15},
            factor_report={"ic_mean": 0.07}, created_at=date(2026, 6, 3))
    run = st.latest()
    assert run.signal == "momentum"
    assert run.strategy_metrics_dict()["annualized_return"] == 0.15
    assert run.factor_report_dict()["ic_mean"] == 0.07
    assert run.params_dict()["topk"] == 8


def test_latest_none_when_empty(session):
    assert BacktestStore(session).latest() is None


def test_list_recent_orders_newest_first(session):
    st = BacktestStore(session)
    st.save(signal="a", start=date(2026, 1, 1), end=date(2026, 2, 1),
            params={}, strategy_metrics={}, factor_report={}, created_at=date(2026, 6, 1))
    st.save(signal="b", start=date(2026, 1, 1), end=date(2026, 2, 1),
            params={}, strategy_metrics={}, factor_report={}, created_at=date(2026, 6, 3))
    runs = st.list_recent(10)
    assert [r.signal for r in runs] == ["b", "a"]
