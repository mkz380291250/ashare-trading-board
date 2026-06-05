"""盘中分钟线采集守护(核心 update_once 可单测)。

启动(照 daily_scheduler_daemon.sh 惯例,经 shell 壳 setsid 脱离 harness):
    setsid bash backend/scripts/minute_updater_daemon.sh >/tmp/minute_updater.out 2>&1 &

节奏:stk_mins 全局限频 1次/分钟 -> universe 有 N 只时每只约每 N 分钟刷新一次。
容器重启需重拉。
"""
import sys
import time
from datetime import datetime, timedelta, timezone, time as dtime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # make `app` importable

from app.data.minute_store import MinuteStore
from app.data.minute_fetch import MinuteFetcher
from app.data.minute_universe import minute_universe
from app.data.rate_limiter import RateLimiter

DEFAULT_FREQ = "1min"
BJ = timezone(timedelta(hours=8))
_FMT = "%Y-%m-%d %H:%M:%S"

# A 股交易时段(北京时间)
_AM = (dtime(9, 30), dtime(11, 30))
_PM = (dtime(13, 0), dtime(15, 0))


def in_trading_session(now_bj: datetime) -> bool:
    if now_bj.weekday() >= 5:  # 周末
        return False
    t = now_bj.time()
    return (_AM[0] <= t <= _AM[1]) or (_PM[0] <= t <= _PM[1])


def update_once(fetcher, store, codes, now: datetime,
                freq: str = DEFAULT_FREQ) -> dict[str, int]:
    """对 codes 各做一次增量拉取并 upsert,返回每只新增行数。
    库内有数据则从 last_time 起增量,否则从当日 09:30 起。"""
    end = now.strftime(_FMT)
    day_open = now.strftime("%Y-%m-%d 09:30:00")
    counts: dict[str, int] = {}
    for code in codes:
        last = store.last_time(code, freq)
        start = last.strftime(_FMT) if last else day_open
        rows = fetcher.fetch(code, freq, start, end)
        if rows:
            store.upsert(code, freq, rows)
        counts[code] = len(rows)
    return counts


def _now_bj() -> datetime:
    return datetime.now(timezone.utc).astimezone(BJ).replace(tzinfo=None)


def main():  # pragma: no cover - 集成路径,核心逻辑见 update_once
    from app.config import get_settings
    from app.db.database import make_engine, make_session_factory
    import app.db.models  # noqa: F401

    settings = get_settings()
    import tushare as ts
    ts.set_token(settings.tushare_token)
    pro = ts.pro_api()
    limiter = RateLimiter(1, 60)  # stk_mins 全局 1次/分钟
    fetcher = MinuteFetcher(pro=pro, limiter=limiter)

    engine = make_engine()
    factory = make_session_factory(engine)
    print(f"[{_now_bj()}] minute_updater daemon started", flush=True)

    while True:
        now = _now_bj()
        if not in_trading_session(now):
            time.sleep(60)
            continue
        with factory() as s:
            codes = minute_universe(s)
            store = MinuteStore(s)
            if not codes:
                time.sleep(60)
                continue
            # round-robin:fetcher 内的全局 RateLimiter 自动把节奏压到 1只/分钟
            counts = update_once(fetcher, store, codes, now)
            got = sum(counts.values())
            print(f"[{now}] round done: {len(codes)} codes, +{got} bars",
                  flush=True)


if __name__ == "__main__":
    main()
