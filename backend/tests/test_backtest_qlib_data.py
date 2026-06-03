from datetime import date
from app.data.source import DailyBar
from app.backtest.qlib_data import export_bars_csv


def _bars():
    return [DailyBar("600519.SH", date(2026, 6, 1), 100, 105, 99, 104, 1000, 1.0),
            DailyBar("600519.SH", date(2026, 6, 2), 104, 108, 103, 107, 1200, 1.0)]


def test_export_bars_csv_uses_qlib_symbol_filename(tmp_path):
    path = export_bars_csv(_bars(), str(tmp_path))
    assert path.name == "SH600519.csv"
    text = path.read_text()
    assert "date,open,high,low,close,volume,factor" in text
    assert "104" in text


def test_export_bars_csv_empty_returns_none(tmp_path):
    assert export_bars_csv([], str(tmp_path)) is None
