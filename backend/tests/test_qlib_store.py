from datetime import date
from app.data.source import DailyBar
from app.data.qlib_store import bars_to_dataframe


def test_bars_to_dataframe_has_expected_columns():
    bars = [DailyBar("600519.SH", date(2026, 1, 2), 10, 11, 9, 10.5, 1000, 1.0)]
    df = bars_to_dataframe(bars)
    assert list(df.columns) == ["date", "open", "high", "low", "close", "volume", "factor"]
    assert df.iloc[0]["close"] == 10.5
    assert df.iloc[0]["factor"] == 1.0
    assert str(df.iloc[0]["date"]) == "2026-01-02"
