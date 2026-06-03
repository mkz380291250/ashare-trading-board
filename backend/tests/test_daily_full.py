import scripts.daily_full as df


def test_run_all_calls_steps_in_order(monkeypatch):
    calls = []
    monkeypatch.setattr(df, "step_quotes", lambda: calls.append("quotes"))
    monkeypatch.setattr(df, "step_qlib", lambda: calls.append("qlib"))
    monkeypatch.setattr(df, "step_tracklist", lambda: calls.append("track"))
    df.run_all()
    assert calls == ["quotes", "qlib", "track"]


def test_run_all_continues_on_failure(monkeypatch):
    calls = []

    def boom():
        raise RuntimeError("quotes failed")
    monkeypatch.setattr(df, "step_quotes", boom)
    monkeypatch.setattr(df, "step_qlib", lambda: calls.append("qlib"))
    monkeypatch.setattr(df, "step_tracklist", lambda: calls.append("track"))
    ok = df.run_all()
    assert calls == ["qlib", "track"]
    assert ok is False
