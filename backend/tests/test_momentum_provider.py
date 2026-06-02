from app.discovery.snapshot import StockData
from app.discovery.providers import MomentumProvider


def _stock(code, closes, highs, turnover, vol_ratio):
    return StockData(code=code, closes=closes, highs=highs,
                     turnover=turnover, vol_ratio=vol_ratio)


def test_momentum_factors():
    # 6 closes so mom_5d = closes[-1]/closes[-6]-1 = 12/10-1 = 0.2
    closes = [10.0, 10.5, 11.0, 11.2, 11.8, 12.0]
    highs = [10.0, 10.5, 11.0, 11.2, 11.8, 12.5]  # 20d-high = 12.5; breakout = 12/12.5
    snap = {"A": _stock("A", closes, highs, turnover=3.0, vol_ratio=1.5)}
    out = MomentumProvider().compute(snap)
    assert set(out.keys()) == {"mom_5d", "turnover", "vol_ratio", "breakout"}
    assert abs(out["mom_5d"]["A"] - 0.2) < 1e-9
    assert out["turnover"]["A"] == 3.0
    assert out["vol_ratio"]["A"] == 1.5
    assert abs(out["breakout"]["A"] - (12.0 / 12.5)) < 1e-9


def test_skips_codes_with_insufficient_history():
    snap = {"B": _stock("B", [10.0, 11.0], [10.0, 11.0], 2.0, 1.0)}  # <6 closes
    out = MomentumProvider().compute(snap)
    assert out["mom_5d"] == {}        # no mom_5d for B
    assert out["turnover"]["B"] == 2.0  # metrics still available


def test_skips_none_metrics():
    closes = [10.0, 10.5, 11.0, 11.2, 11.8, 12.0]
    snap = {"C": StockData("C", closes, closes, turnover=None, vol_ratio=None)}
    out = MomentumProvider().compute(snap)
    assert "C" not in out["turnover"] and "C" not in out["vol_ratio"]
    assert "C" in out["mom_5d"]
