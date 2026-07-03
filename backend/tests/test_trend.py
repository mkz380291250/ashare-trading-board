from app.decision.trend import is_uptrend


def test_rejects_single_direction_downtrend():
    # 单边下跌:收盘远低于均线 → 飞刀,拒绝
    closes = [25.0 - i * 0.5 for i in range(20)]   # 25 → 15.5 一路下行
    assert is_uptrend(closes, window=20) is False


def test_accepts_price_above_ma():
    # 上行趋势:收盘在均线之上 → 接受
    closes = [10.0 + i * 0.3 for i in range(20)]   # 10 → 15.7 一路上行
    assert is_uptrend(closes, window=20) is True


def test_accepts_basing_near_ma_within_tol():
    closes = [10.0] * 19 + [9.95]                  # 贴着均线略下,tol 内放行
    assert is_uptrend(closes, window=20, tol=0.02) is True
    assert is_uptrend(closes, window=20, tol=0.0) is False


def test_insufficient_data_is_rejected():
    # 数据不足无法确认趋势 → 保守拒绝(不买)
    assert is_uptrend([10.0, 11.0], window=20) is False
    assert is_uptrend([], window=20) is False


def test_uses_last_window_only():
    # 只看最近 window 根:早期暴跌但近端已在均线上 → 接受
    closes = [50.0, 40.0, 30.0] + [10.0 + i * 0.2 for i in range(20)]
    assert is_uptrend(closes, window=20) is True
