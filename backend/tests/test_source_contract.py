from datetime import date
from app.data.source import DailyBar, MarketDataSource


class FakeSource(MarketDataSource):
    def get_daily_bars(self, code, start, end):
        return [DailyBar(code=code, trade_date=date(2026, 5, 29),
                         open=10, high=11, low=9, close=10.5,
                         volume=1000, adj_factor=1.0)]


def test_dailybar_fields_and_interface():
    src = FakeSource()
    bars = src.get_daily_bars("600519.SH", date(2026, 5, 1), date(2026, 5, 30))
    assert len(bars) == 1
    b = bars[0]
    assert b.code == "600519.SH"
    assert b.close == 10.5
    assert b.adj_factor == 1.0
