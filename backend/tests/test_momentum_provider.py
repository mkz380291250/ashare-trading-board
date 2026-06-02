from app.discovery.snapshot import StockData
from app.discovery.providers import MomentumProvider


def _stock(code, closes, highs, volumes, turnover):
    return StockData(code=code, closes=closes, highs=highs,
                     volumes=volumes, turnover=turnover)


def test_momentum_factors():
    # 6 closes so mom_5d = closes[-1]/closes[-6]-1 = 12/10-1 = 0.2
    closes = [10.0, 10.5, 11.0, 11.2, 11.8, 12.0]
    highs = [10.0, 10.5, 11.0, 11.2, 11.8, 12.5]  # 20d-high = 12.5; breakout = 12/12.5
    volumes = [100.0, 100.0, 100.0, 100.0, 100.0, 200.0]  # 量比 = 200 / avg(prev5=100) = 2.0
    snap = {"A": _stock("A", closes, highs, volumes, turnover=3.0)}
    out = MomentumProvider().compute(snap)
    assert set(out.keys()) == {"mom_5d", "turnover", "vol_ratio", "breakout"}
    assert abs(out["mom_5d"]["A"] - 0.2) < 1e-9
    assert out["turnover"]["A"] == 3.0
    assert abs(out["vol_ratio"]["A"] - 2.0) < 1e-9
    assert abs(out["breakout"]["A"] - (12.0 / 12.5)) < 1e-9


def test_skips_codes_with_insufficient_history():
    snap = {"B": _stock("B", [10.0, 11.0], [10.0, 11.0], [100.0, 100.0], 2.0)}  # <6 bars
    out = MomentumProvider().compute(snap)
    assert out["mom_5d"] == {}        # no mom_5d for B
    assert out["vol_ratio"] == {}     # no 量比 either (needs >=6 volumes)
    assert out["turnover"]["B"] == 2.0  # turnover still available


def test_skips_none_turnover_but_keeps_computed_factors():
    closes = [10.0, 10.5, 11.0, 11.2, 11.8, 12.0]
    vols = [100.0, 100.0, 100.0, 100.0, 100.0, 150.0]
    snap = {"C": StockData("C", closes, closes, vols, turnover=None)}
    out = MomentumProvider().compute(snap)
    assert "C" not in out["turnover"]        # turnover is None -> excluded
    assert "C" in out["mom_5d"] and "C" in out["vol_ratio"]  # computed factors fine
