"""盘中分钟线采集守护(核心 update_once 可单测)。

启动(照 daily_scheduler_daemon.sh 惯例,经 shell 壳 setsid 脱离 harness):
    setsid bash backend/scripts/minute_updater_daemon.sh >/tmp/minute_updater.out 2>&1 &

数据源:东方财富分钟线(免费、无 tushare 频次限制)。日线仍走 tushare,不变。
每轮对 universe 的每只 × 每个周期各拉一次,礼貌限速 ≤1次/秒。容器重启需重拉。
"""
import sys
import time
from datetime import datetime, timedelta, timezone, time as dtime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # make `app` importable

from app.data.minute_store import MinuteStore
from app.data.minute_fetch_eastmoney import EastMoneyMinuteFetcher
from app.data.minute_universe import minute_universe
from app.data.rate_limiter import RateLimiter

DEFAULT_FREQ = "1min"
FREQS = ("1min", "5min", "15min", "30min", "60min")
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


def backfill_once(fetcher, store, codes, freqs=FREQS) -> dict[str, int]:
    """一次性回填:对每只 × 每周期拉最近一批分钟线(start=None 取全部 lmt 条),
    不受交易时段限制,用于初始化/收盘后补数据让图先有内容。"""
    counts: dict[str, int] = {}
    for code in codes:
        got = 0
        for freq in freqs:
            rows = fetcher.fetch(code, freq, None, None)
            if rows:
                store.upsert(code, freq, rows)
                got += len(rows)
        counts[code] = got
    return counts


def _now_bj() -> datetime:
    return datetime.now(timezone.utc).astimezone(BJ).replace(tzinfo=None)


def main():  # pragma: no cover - 集成路径,核心逻辑见 update_once
    from app.config import get_settings
    from app.db.database import make_engine, make_session_factory
    import app.db.models  # noqa: F401

    get_settings()  # validate config/env
    limiter = RateLimiter(1, 2)  # 礼貌限速:东财每2秒≤1次(避免触发IP限流)
    fetcher = EastMoneyMinuteFetcher(limiter=limiter)

    engine = make_engine()
    factory = make_session_factory(engine)
    print(f"[{_now_bj()}] minute_updater daemon started (EastMoney)", flush=True)

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
            got = 0
            for freq in FREQS:
                counts = update_once(fetcher, store, codes, now, freq=freq)
                got += sum(counts.values())
            print(f"[{now}] round done: {len(codes)} codes x{len(FREQS)} freq, "
                  f"+{got} bars", flush=True)


if __name__ == "__main__":
    main()
