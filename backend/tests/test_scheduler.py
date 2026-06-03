from app.scheduler import build_scheduler


def test_build_scheduler_registers_daily_job():
    calls = []
    sched = build_scheduler(lambda: calls.append("ran"), hour=16, minute=0)
    jobs = sched.get_jobs()
    assert len(jobs) == 1
    trig = str(jobs[0].trigger)
    assert "hour='16'" in trig and "minute='0'" in trig
    assert "Asia/Shanghai" in trig
    jobs[0].func()
    assert calls == ["ran"]
    sched.shutdown(wait=False)
