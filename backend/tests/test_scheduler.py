from app.scheduler import build_scheduler


def test_build_scheduler_registers_daily_job():
    calls = []
    sched = build_scheduler(lambda: calls.append("ran"), hour=16, minute=0)
    assert str(sched.timezone) == "Asia/Shanghai"
    jobs = sched.get_jobs()
    assert len(jobs) == 1
    assert jobs[0].id == "daily_full"
    fields = {f.name: str(f) for f in jobs[0].trigger.fields if str(f) != "*"}
    assert fields["hour"] == "16" and fields["minute"] == "0"
    assert str(jobs[0].trigger.timezone) == "Asia/Shanghai"
    jobs[0].func()
    assert calls == ["ran"]
    # scheduler was never started, so no shutdown needed
