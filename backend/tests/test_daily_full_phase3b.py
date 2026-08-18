# backend/tests/test_daily_full_phase3b.py
import scripts.daily_full as df


def test_run_all_appends_step_policy(monkeypatch):
    calls = []
    for name in ("step_quotes", "step_qlib", "step_tracklist", "step_select",
                 "step_rebalance", "step_mark", "step_attribution", "step_policy"):
        monkeypatch.setattr(df, name, (lambda n=name: lambda: calls.append(n))())
    df.run_all()
    assert calls[-1] == "step_policy"
    assert calls == ["step_quotes", "step_qlib", "step_tracklist", "step_select",
                     "step_rebalance", "step_mark", "step_attribution", "step_policy"]
