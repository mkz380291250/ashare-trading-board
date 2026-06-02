from datetime import date
import pandas as pd
from app.data.tushare_source import TushareSource


class FakePro:
    def daily(self, ts_code, start_date, end_date):
        return pd.DataFrame({
            "ts_code": [ts_code, ts_code],
            "trade_date": ["20260103", "20260102"],   # tushare returns desc
            "open": [11.0, 10.0], "high": [11.5, 10.5],
            "low": [10.8, 9.8], "close": [11.0, 10.0], "vol": [2000.0, 1000.0],
        })

    def adj_factor(self, ts_code, start_date, end_date):
        return pd.DataFrame({
            "trade_date": ["20260103", "20260102"],
            "adj_factor": [2.0, 1.0],
        })


def test_returns_sorted_bars_with_factor():
    src = TushareSource(pro=FakePro())
    bars = src.get_daily_bars("600519.SH", date(2026, 1, 1), date(2026, 1, 5))
    assert [b.trade_date for b in bars] == [date(2026, 1, 2), date(2026, 1, 3)]  # ascending
    assert bars[0].close == 10.0 and bars[0].adj_factor == 1.0
    assert bars[1].close == 11.0 and bars[1].adj_factor == 2.0
    assert bars[1].volume == 2000.0
