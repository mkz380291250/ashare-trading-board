from app.screener.earnings import Earnings, TushareEarningsSource, passes_earnings


def test_passes_earnings_rule():
    assert passes_earnings(Earnings(np_yoy=25.0, rev_yoy=5.0)) is True
    assert passes_earnings(Earnings(np_yoy=20.0, rev_yoy=5.0)) is True   # >=20
    assert passes_earnings(Earnings(np_yoy=19.9, rev_yoy=5.0)) is False
    assert passes_earnings(Earnings(np_yoy=30.0, rev_yoy=0.0)) is False  # rev must be >0
    assert passes_earnings(None) is False


class FakePro:
    def fina_indicator(self, ts_code, **kw):
        import pandas as pd
        return pd.DataFrame({"end_date": ["20251231"], "netprofit_yoy": [25.0],
                             "or_yoy": [5.0]})


def test_tushare_earnings_latest():
    src = TushareEarningsSource(pro=FakePro())
    e = src.latest("600519.SH")
    assert e.np_yoy == 25.0 and e.rev_yoy == 5.0
