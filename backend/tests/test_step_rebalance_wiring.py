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
