from app.attribution.equity import current_drawdown, rolling_hit_rate


def test_drawdown_from_peak():
    # 峰值 120,末值 102 → -15%
    assert abs(current_drawdown([100, 120, 110, 102]) - (-0.15)) < 1e-9


def test_drawdown_new_high_zero():
    assert current_drawdown([100, 110, 130]) == 0.0


def test_drawdown_empty_none():
    assert current_drawdown([]) is None


def test_drawdown_recovers_after_trough():
    # 触底反弹:峰值100,谷底80,回升到90 → 当前回撤 = 90/100-1 = -10%(非历史最大-20%)
    assert abs(current_drawdown([100, 80, 90]) - (-0.10)) < 1e-9


def test_rolling_hit_rate_ignores_none():
    assert rolling_hit_rate([True, False, None, True]) == 2 / 3


def test_rolling_hit_rate_no_sample_none():
    assert rolling_hit_rate([None, None]) is None
