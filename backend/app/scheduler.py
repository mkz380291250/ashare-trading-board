"""APScheduler 封装:每天指定的北京时间触发一个回调。"""
from collections.abc import Callable
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger


def build_scheduler(job: Callable[[], object], hour: int = 16,
                    minute: int = 0) -> BackgroundScheduler:
    sched = BackgroundScheduler(timezone="Asia/Shanghai")
    trigger = CronTrigger(hour=hour, minute=minute, timezone="Asia/Shanghai")
    sched.add_job(job, trigger, id="daily_full", replace_existing=True)
    return sched


def start_scheduler(job: Callable[[], object], hour: int = 16,
                    minute: int = 0) -> BackgroundScheduler:
    sched = build_scheduler(job, hour=hour, minute=minute)
    sched.start()
    return sched
