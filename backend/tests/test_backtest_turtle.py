import numpy as np
import pandas as pd
import pytest
from app.backtest.turtle import Panel, Params, run_turtle, metrics


def _panel(T=30, N=3):
    dates = pd.bdate_range("2024-01-01", periods=T).values
    close = np.full((T, N), 10.0, dtype="float32")
    return Panel(dates=dates, codes=[f"S{i}" for i in range(N)],
                 open=close.copy(), high=close * 1.01, low=close * 0.99, close=close,
                 raw_open=close.copy(), raw_pre_close=np.vstack([close[:1], close[:-1]]),
                 score=np.tile(np.array([3., 2., 1.], dtype="float32"), (T, 1)),
                 atr=np.full((T, N), 0.2, dtype="float32"), hi20=close * 0.98,
                 limit=np.full((T, N), 0.2, dtype="float32"))


def _by(res, code):
    return next(t for t in res.trades if t.code == code)


def test_entry_next_open_and_one_per_day():
    p = _panel()
    res = run_turtle(p, Params(slots=3, exit="fixed", sl=0.5, rr=100))   # 永不触发
    ts = sorted(res.trades, key=lambda t: t.entry_i)
    assert [t.entry_i for t in ts] == [1, 2, 3]          # 第 0 天信号 → 第 1 天开盘;每天 1 仓;3 槽满
    assert [t.code for t in ts] == ["S0", "S1", "S2"]
    assert all(t.reason == "end" for t in ts)
    assert all(t.shares % 100 == 0 and t.shares > 0 for t in ts)
    assert len(res.nav) == 30 and res.nav[0] == pytest.approx(1_000_000.0)


def test_fixed_stop_gap_open_vs_intraday():
    p = _panel()
    p.low[5, 0] = 9.3                                    # 盘中触及 6% 止损(entry 10 → 9.4)
    p.open[10, 1] = 9.0
    p.low[10, 1] = 8.9                                   # 跳空低开穿过止损
    res = run_turtle(p, Params(slots=2, sl=0.06, rr=100))
    t0, t1 = _by(res, "S0"), _by(res, "S1")
    assert (t0.exit_i, t0.reason) == (5, "stop") and t0.exit_px == pytest.approx(9.4)
    assert (t1.exit_i, t1.reason) == (10, "stop") and t1.exit_px == pytest.approx(9.0)


def test_fixed_tp_and_same_day_both_prefers_stop():
    p = _panel()
    p.high[6, 0] = 11.5                                  # tp = 10*(1+0.06*2) = 11.2
    p.high[8, 1] = 11.5
    p.low[8, 1] = 9.0                                    # 同日双触 → 止损
    res = run_turtle(p, Params(slots=2, sl=0.06, rr=2))
    t0, t1 = _by(res, "S0"), _by(res, "S1")
    assert t0.reason == "tp" and t0.exit_i == 6 and t0.exit_px == pytest.approx(11.2)
    assert t1.reason == "stop" and t1.exit_px == pytest.approx(9.4)


def test_tp_gap_open_above_tp_uses_open():
    p = _panel()
    p.open[6, 0] = 11.8
    p.high[6, 0] = 11.9
    res = run_turtle(p, Params(slots=1, sl=0.06, rr=2))
    t = res.trades[0]
    assert t.reason == "tp" and t.exit_px == pytest.approx(11.8)


def test_atr_trailing_moves_up():
    p = _panel()
    p.close[3:, 0] = 12.0
    p.high[3:, 0] = 12.1
    p.low[3:, 0] = 11.9
    p.open[3:, 0] = 12.0
    p.low[9, 0] = 11.5                                   # 12 − 2×0.2 = 11.6 → 触发 trail
    res = run_turtle(p, Params(slots=1, exit="atr", k_stop=2, k_trail=2))
    t = res.trades[0]
    assert (t.reason, t.exit_i) == ("trail", 9) and t.exit_px == pytest.approx(11.6)


def test_atr_initial_stop_before_any_rise():
    p = _panel()
    p.low[4, 0] = 9.5                                    # 10 − 2×0.2 = 9.6
    res = run_turtle(p, Params(slots=1, exit="atr", k_stop=2, k_trail=3))
    t = res.trades[0]
    assert (t.reason, t.exit_i) == ("stop", 4) and t.exit_px == pytest.approx(9.6)


def test_time_stop_next_open_and_limit_down_defers():
    p = _panel()
    p.raw_open[4, 0] = 8.0
    p.raw_pre_close[4, 0] = 10.0                         # 第 4 天跌停开盘,不能卖
    res = run_turtle(p, Params(slots=1, sl=0.5, rr=100, max_hold=2))
    t = res.trades[0]
    # 第 1 天买,持有第 2、3 天满 2 天 → 第 4 天开盘想卖被跌停顺延 → 第 5 天开盘
    assert (t.entry_i, t.exit_i, t.reason) == (1, 5, "time")


def test_limit_up_open_skips_entry_then_retries_next_day():
    p = _panel()
    p.raw_open[1, 0] = 12.0
    p.raw_pre_close[1, 0] = 10.0                         # S0 第 1 天一字涨停买不到
    res = run_turtle(p, Params(slots=1, sl=0.5, rr=100))
    first = min(res.trades, key=lambda t: t.entry_i)
    assert (first.entry_i, first.code) == (2, "S0")      # 当天不补,第 2 天重选仍是 S0


def test_delisting_exits_at_last_close():
    p = _panel()
    p.close[15:, 0] = np.nan
    p.open[15:, 0] = np.nan
    p.high[15:, 0] = np.nan
    p.low[15:, 0] = np.nan
    p.close[14, 0] = 7.0
    res = run_turtle(p, Params(slots=1, sl=0.5, rr=100))
    t = _by(res, "S0")
    assert t.reason == "end" and t.exit_i == 14 and t.exit_px == pytest.approx(7.0)
    assert len(res.trades) >= 2                           # 槽位释放后继续开仓


def test_breakout_entry_requires_new_high():
    p = _panel()
    p.hi20[:, :] = 10.5                                  # 无人突破
    res = run_turtle(p, Params(slots=1, entry="breakout", sl=0.5, rr=100))
    assert res.trades == []
    p.close[5, 2] = 10.6                                 # 只有 S2 突破
    res = run_turtle(p, Params(slots=1, entry="breakout", sl=0.5, rr=100))
    assert len(res.trades) == 1 and res.trades[0].code == "S2" and res.trades[0].entry_i == 6


def test_metrics_basic():
    p = _panel()
    p.high[6, 0] = 11.5
    res = run_turtle(p, Params(slots=1, sl=0.06, rr=2))
    m = metrics(res, p.dates, None)
    assert m["n_trades"] >= 1 and 0 <= m["win_rate"] <= 1 and m["ann"] > 0 and m["mdd"] <= 0
    assert m["profit_factor"] > 1 and m["exposure"] > 0
    m2 = metrics(res, p.dates, np.zeros(len(p.dates)))
    assert m2["excess_ann"] == pytest.approx(m2["ann"])
