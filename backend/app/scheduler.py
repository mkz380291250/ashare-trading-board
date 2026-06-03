"""APScheduler 封装:每天指定的北京时间触发一个回调。"""
from apscheduler.schedulers import SchedulerNotRunningError
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger


class SafeBackgroundScheduler(BackgroundScheduler):
    """shutdown 在调度器尚未 start 时不报错(便于构建后直接清理)。"""

    def shutdown(self, wait: bool = True) -> None:
        try:
            super().shutdown(wait=wait)
        except SchedulerNotRunningError:
            pass


class TZCronTrigger(CronTrigger):
    """CronTrigger whose str() also exposes the timezone.

    APScheduler 3.x 的 CronTrigger.__str__ 只包含 cron 字段(如
    cron[hour='16', minute='0']),时区只在 __repr__ 中出现。这里在
    __str__ 中附带时区,便于调试/日志,也保证调用方能从 str() 读到时区。
    """

    def __str__(self) -> str:
        base = super().__str__()  # 形如 cron[hour='16', minute='0']
        return base[:-1] + ", timezone='{}']".format(self.timezone)


def build_scheduler(job, hour: int = 16, minute: int = 0) -> BackgroundScheduler:
    sched = SafeBackgroundScheduler(timezone="Asia/Shanghai")
    trigger = TZCronTrigger(hour=hour, minute=minute, timezone="Asia/Shanghai")
    sched.add_job(job, trigger, id="daily_full", replace_existing=True)
    return sched


def start_scheduler(job, hour: int = 16, minute: int = 0) -> BackgroundScheduler:
    sched = build_scheduler(job, hour=hour, minute=minute)
    sched.start()
    return sched
