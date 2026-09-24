def test_run_all_uses_rebalance_step_not_debate():
    # 结构守卫:夜链已切系统化再平衡,不应再挂旧的逐股 debate step
    import inspect
    import scripts.daily_full as df
    src = inspect.getsource(df.run_all)
    assert '"rebalance"' in src and "step_rebalance" in src
    assert '("debate"' not in src
    assert hasattr(df, "step_rebalance")


def test_step_rebalance_skips_non_rebalance_day(monkeypatch, capsys):
    # 非再平衡日:step 早退,不触发任何重活(不建 session/不调编排)
    import scripts.daily_full as df
    from datetime import date

    called = {"rebalanced": False}
    monkeypatch.setattr(df, "rebalance_portfolio",
                        lambda *a, **k: called.__setitem__("rebalanced", True))
    # 隔离:不连真库;伪造 as_of 为周二、settings 周一再平衡
    monkeypatch.setattr(df, "_session", lambda: object())
    monkeypatch.setattr(df, "QuoteStore", lambda s: object())
    monkeypatch.setattr(df, "_as_of_for_rebalance", lambda store: date(2026, 8, 18))
    df.step_rebalance()
    assert called["rebalanced"] is False
    assert "REBALANCE_SKIP" in capsys.readouterr().out


def _gate_fixture(monkeypatch, on, changed, prev=True):
    import scripts.daily_full as df
    from app.portfolio.trend_gate import GateEval
    from datetime import date
    g = GateEval(on=on, prev_on=prev, close=100.0, ma=100.0, ratio=0.0, as_of=date(2026, 8, 18))
    if changed:
        g = GateEval(on=on, prev_on=(not on), close=100.0, ma=100.0, ratio=0.0, as_of=date(2026, 8, 18))
    monkeypatch.setattr(df, "_gate_eval", lambda session, s, as_of: g)
    return df


def test_gate_off_liquidates_and_skips_rebalance(monkeypatch, capsys):
    df = _gate_fixture(monkeypatch, on=False, changed=True)
    from datetime import date
    called = {"rebalanced": False, "liq": None}
    monkeypatch.setattr(df, "rebalance_portfolio", lambda *a, **k: called.__setitem__("rebalanced", True))
    monkeypatch.setattr(df, "_as_of_for_rebalance", lambda store: date(2026, 8, 17))   # 周一也不买
    import app.portfolio.trend_gate as tg
    monkeypatch.setattr(tg, "liquidate_all", lambda *a, **k: called.__setitem__("liq", True) or ["300001.SZ"])
    import app.policy.guardrails as gr
    monkeypatch.setattr(gr, "already_recorded", lambda *a, **k: True)
    monkeypatch.setattr(df, "build_daily_summary", lambda *a, **k: "summary")

    class _S:
        def scalars(self, q):
            class _R:
                def all(self_inner): return []
            return _R()
    monkeypatch.setattr(df, "_session", lambda: _S())
    monkeypatch.setattr(df, "QuoteStore", lambda s: object())
    monkeypatch.setattr(df, "PaperBroker", lambda s: object())
    df.step_rebalance()
    out = capsys.readouterr().out
    assert called["liq"] is True and called["rebalanced"] is False
    assert "'gate': 'OFF'" in out and "GATE 2026-08-17" in out


def test_gate_reentry_forces_buy_on_non_rebalance_day(monkeypatch, capsys):
    df = _gate_fixture(monkeypatch, on=True, changed=True)
    from datetime import date
    reached = {"after_gate": False}
    monkeypatch.setattr(df, "_as_of_for_rebalance", lambda store: date(2026, 8, 18))   # 周二
    import app.policy.guardrails as gr
    monkeypatch.setattr(gr, "already_recorded", lambda *a, **k: True)

    class _S:
        def scalar(self, q):
            reached["after_gate"] = True
            raise RuntimeError("stop-here")          # 走到了选股产物查询=已越过闸与周判定
    monkeypatch.setattr(df, "_session", lambda: _S())
    monkeypatch.setattr(df, "QuoteStore", lambda s: object())
    import pytest
    with pytest.raises(RuntimeError, match="stop-here"):
        df.step_rebalance()
    assert reached["after_gate"] and "GATE_REENTRY" in capsys.readouterr().out


def test_gate_on_unchanged_keeps_weekday_rule(monkeypatch, capsys):
    df = _gate_fixture(monkeypatch, on=True, changed=False)
    from datetime import date
    monkeypatch.setattr(df, "_as_of_for_rebalance", lambda store: date(2026, 8, 18))   # 周二
    monkeypatch.setattr(df, "_session", lambda: object())
    monkeypatch.setattr(df, "QuoteStore", lambda s: object())
    df.step_rebalance()
    assert "REBALANCE_SKIP" in capsys.readouterr().out
