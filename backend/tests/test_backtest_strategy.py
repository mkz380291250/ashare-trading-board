import pandas as pd
from app.backtest.strategy import summarize_report


def test_summarize_report_extracts_metrics():
    idx = pd.date_range("2026-01-01", periods=3, freq="D")
    report = pd.DataFrame({"return": [0.01, -0.02, 0.03],
                           "bench": [0.005, -0.01, 0.01]}, index=idx)
    analysis = pd.DataFrame(
        {"risk": [0.15, 1.2, -0.08]},
        index=["annualized_return", "information_ratio", "max_drawdown"])
    out = summarize_report(report, analysis)
    assert abs(out["annualized_return"] - 0.15) < 1e-9
    assert abs(out["information_ratio"] - 1.2) < 1e-9
    assert abs(out["max_drawdown"] + 0.08) < 1e-9
    assert out["days"] == 3
    assert abs(out["cum_return"] - ((1.01 * 0.98 * 1.03) - 1.0)) < 1e-6


def test_summarize_report_missing_metric_is_none():
    idx = pd.date_range("2026-01-01", periods=1, freq="D")
    report = pd.DataFrame({"return": [0.0], "bench": [0.0]}, index=idx)
    analysis = pd.DataFrame({"risk": [0.1]}, index=["annualized_return"])
    out = summarize_report(report, analysis)
    assert out["annualized_return"] == 0.1
    assert out["information_ratio"] is None
