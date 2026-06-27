# backend/tests/test_daily_full_phase2.py
import scripts.daily_full as df


def test_run_all_includes_phase2_steps_in_order(monkeypatch):
    calls = []
    for name in ("step_quotes", "step_qlib", "step_tracklist",
                 "step_select", "step_debate", "step_mark"):
        monkeypatch.setattr(df, name, (lambda n=name: lambda: calls.append(n))())
    df.run_all()
    assert calls == ["quotes", "qlib", "track", "select", "debate", "mark"] or \
           calls == ["step_quotes", "step_qlib", "step_tracklist",
                     "step_select", "step_debate", "step_mark"]


def test_run_all_isolates_phase2_step_failure(monkeypatch):
    calls = []
    monkeypatch.setattr(df, "step_quotes", lambda: calls.append("step_quotes"))
    monkeypatch.setattr(df, "step_qlib", lambda: calls.append("step_qlib"))
    monkeypatch.setattr(df, "step_tracklist", lambda: calls.append("step_tracklist"))

    def boom(): raise RuntimeError("select failed")
    monkeypatch.setattr(df, "step_select", boom)
    monkeypatch.setattr(df, "step_debate", lambda: calls.append("step_debate"))
    monkeypatch.setattr(df, "step_mark", lambda: calls.append("step_mark"))
    ok = df.run_all()
    assert "step_debate" in calls and "step_mark" in calls    # 后续步不被阻断
    assert ok is False
