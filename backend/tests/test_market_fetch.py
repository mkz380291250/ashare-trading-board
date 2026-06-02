from datetime import date
import pandas as pd
from app.data.market_fetch import MarketFetcher


class FakePro:
    def daily(self, trade_date):
        return pd.DataFrame({
            "ts_code": ["600519.SH", "000001.SZ"],
            "open": [1270.0, 11.0], "high": [1329.0, 11.5],
            "low": [1270.0, 10.8], "close": [1326.0, 11.0],
            "pre_close": [1275.98, 10.9], "vol": [76478.0, 2000.0],
            "amount": [1.0e7, 2.2e4],
        })

    def daily_basic(self, trade_date):
        # tushare daily_basic ALSO returns close/open etc. -> must not collide
        return pd.DataFrame({
            "ts_code": ["600519.SH", "000001.SZ"],
            "close": [9999.0, 9999.0],  # decoy: must be ignored (daily wins)
            "turnover_rate": [0.6, 1.1], "volume_ratio": [1.2, 0.9],
            "circ_mv": [1.0e9, 2.0e8], "total_mv": [1.6e9, 3.0e8],
            "pe": [30.0, 5.0], "pb": [9.0, 0.6],
        })

    def adj_factor(self, trade_date):
        return pd.DataFrame({
            "ts_code": ["600519.SH", "000001.SZ"],
            "adj_factor": [8.4464, 12.3],
        })


class CountingLimiter:
    def __init__(self): self.n = 0
    def acquire(self): self.n += 1


def test_fetch_day_merges_three_sources():
    lim = CountingLimiter()
    f = MarketFetcher(pro=FakePro(), limiter=lim)
    rows = f.fetch_day(date(2026, 5, 29))
    assert lim.n == 3                     # one acquire per tushare call
    by = {r["code"]: r for r in rows}
    assert len(rows) == 2
    mt = by["600519.SH"]
    assert mt["trade_date"] == date(2026, 5, 29)
    assert mt["close"] == 1326.0 and mt["adj_factor"] == 8.4464
    assert mt["turnover_rate"] == 0.6 and mt["pb"] == 9.0


def test_missing_adj_factor_defaults_to_one():
    class NoAdjPro(FakePro):
        def adj_factor(self, trade_date):
            return pd.DataFrame({"ts_code": ["600519.SH"], "adj_factor": [8.4464]})
    f = MarketFetcher(pro=NoAdjPro(), limiter=CountingLimiter())
    by = {r["code"]: r for r in f.fetch_day(date(2026, 5, 29))}
    assert by["000001.SZ"]["adj_factor"] == 1.0   # no factor row -> default 1.0
