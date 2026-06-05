import pandas as pd
from app.data.financials import FinancialsSource


class FakePro:
    def income(self, ts_code, start_date=None, end_date=None):
        return pd.DataFrame({"end_date": ["20251231", "20260331"],
                             "revenue": [4.0e8, 5.0e8],
                             "n_income_attr_p": [4.0e7, 5.7e7]})

    def balancesheet(self, ts_code, start_date=None, end_date=None):
        return pd.DataFrame({"end_date": ["20251231", "20260331"],
                             "total_assets": [3.0e9, 3.5e9],
                             "total_liab": [1.0e9, 1.28e9],
                             "goodwill": [3.4e7, 3.4e7],
                             "accounts_receiv": [8.0e8, 8.58e8]})

    def cashflow(self, ts_code, start_date=None, end_date=None):
        return pd.DataFrame({"end_date": ["20251231", "20260331"],
                             "n_cashflow_act": [1.2e8, 1.7e8]})

    def fina_indicator(self, ts_code, start_date=None, end_date=None):
        return pd.DataFrame({"end_date": ["20251231", "20260331"],
                             "roe": [3.0, 2.59], "grossprofit_margin": [25.0, 26.36],
                             "debt_to_assets": [33.0, 36.42],
                             "netprofit_yoy": [10.0, -3.21], "or_yoy": [8.0, 5.52]})


def test_summary_picks_latest_period_and_converts_units():
    f = FinancialsSource(FakePro()).summary("300566.SZ")
    assert f["报告期"] == "20260331"
    assert f["营收_亿"] == 5.0 and f["归母净利_亿"] == 0.57
    assert f["净利同比"] == -3.21 and f["营收同比"] == 5.52
    assert f["毛利率"] == 26.36 and f["ROE"] == 2.59 and f["资产负债率"] == 36.42
    assert f["经营现金流_亿"] == 1.7
    assert f["现金流净利比"] == round(1.7e8 / 5.7e7, 2)   # 盈利质量
    assert f["商誉_亿"] == 0.34 and f["应收账款_亿"] == 8.58


def test_summary_swallows_errors_per_statement():
    class PartialPro(FakePro):
        def cashflow(self, *a, **k):
            raise RuntimeError("rate limit")
    f = FinancialsSource(PartialPro()).summary("X")
    assert "营收_亿" in f and "经营现金流_亿" not in f  # 现金流取不到,其余仍在


def test_summary_none_when_all_empty():
    class EmptyPro:
        def income(self, *a, **k): return pd.DataFrame()
        def balancesheet(self, *a, **k): return pd.DataFrame()
        def cashflow(self, *a, **k): return pd.DataFrame()
        def fina_indicator(self, *a, **k): return pd.DataFrame()
    assert FinancialsSource(EmptyPro()).summary("X") is None


class _Lim:
    def __init__(self): self.calls = 0
    def acquire(self): self.calls += 1


def test_limiter_called_per_statement():
    lim = _Lim()
    FinancialsSource(FakePro(), limiter=lim).summary("X")
    assert lim.calls == 4   # income/balancesheet/cashflow/fina_indicator
