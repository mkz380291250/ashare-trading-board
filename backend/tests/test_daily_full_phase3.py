import scripts.daily_full as df


def test_run_all_appends_step_attribution(monkeypatch):
    calls = []
    for name in ("step_quotes", "step_qlib", "step_tracklist",
                 "step_select", "step_debate", "step_mark", "step_attribution"):
        monkeypatch.setattr(df, name, (lambda n=name: lambda: calls.append(n))())
    df.run_all()
    assert calls[-1] == "step_attribution"
    assert calls == ["step_quotes", "step_qlib", "step_tracklist",
                     "step_select", "step_debate", "step_mark", "step_attribution"]
