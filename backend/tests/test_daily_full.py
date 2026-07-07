import scripts.daily_full as df


def test_run_all_calls_steps_in_order(monkeypatch):
    calls = []
    monkeypatch.setattr(df, "step_quotes", lambda: calls.append("quotes"))
    monkeypatch.setattr(df, "step_qlib", lambda: calls.append("qlib"))
    monkeypatch.setattr(df, "step_tracklist", lambda: calls.append("track"))
    monkeypatch.setattr(df, "step_select", lambda: None)
    monkeypatch.setattr(df, "step_debate", lambda: None)
    monkeypatch.setattr(df, "step_mark", lambda: None)
    df.run_all()
    assert calls == ["quotes", "qlib", "track"]


def test_run_all_continues_on_failure(monkeypatch):
    calls = []

    def boom():
        raise RuntimeError("quotes failed")
    monkeypatch.setattr(df, "step_quotes", boom)
    monkeypatch.setattr(df, "step_qlib", lambda: calls.append("qlib"))
    monkeypatch.setattr(df, "step_tracklist", lambda: calls.append("track"))
    monkeypatch.setattr(df, "step_select", lambda: None)
    monkeypatch.setattr(df, "step_debate", lambda: None)
    monkeypatch.setattr(df, "step_mark", lambda: None)
    ok = df.run_all()
    assert calls == ["qlib", "track"]
    assert ok is False


def test_retry_on_usage_limit_waits_then_succeeds():
    # 限额中止后应长等重试(限额按时段重置),而非立刻放弃
    from app.decision.llm import UsageLimitError
    from scripts.daily_full import _retry_on_usage_limit
    calls = {"n": 0}
    naps = []

    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise UsageLimitError("hit your session limit")
        return "SUMMARY"

    assert _retry_on_usage_limit(flaky, retries=6, wait_s=1800,
                                 sleep=naps.append) == "SUMMARY"
    assert calls["n"] == 3 and naps == [1800, 1800]


def test_retry_on_usage_limit_gives_up_after_retries():
    import pytest
    from app.decision.llm import UsageLimitError
    from scripts.daily_full import _retry_on_usage_limit

    def always_limited():
        raise UsageLimitError("hit your session limit")

    with pytest.raises(UsageLimitError):
        _retry_on_usage_limit(always_limited, retries=2, wait_s=1,
                              sleep=lambda s: None)
