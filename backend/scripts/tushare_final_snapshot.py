"""tushare 到期前(2026-09-16)最后一次全量落库,之后行情走免费源。
两条流可并行跑(tushare 限频按接口计):
  python scripts/tushare_final_snapshot.py quotes   # 日线:补 2021-02-25..2023-05-31 缺口、
                                                    #   补 2026 年量比为空的日子、追溯 2010~2020 → ashare.db daily_quotes
  python scripts/tushare_final_snapshot.py extra    # 基础信息/日历/指数/财报/分红/资金流 → data/tushare_extra.db
都可重复运行(跳过已有)。日志 data/tushare_snapshot.log。
"""
import argparse
import sqlite3
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd
from sqlalchemy import select, func, insert, text

from app.config import get_settings
from app.db.database import make_engine, make_session_factory
from app.db.models import DailyQuote, IngestedDay
from app.data.market_fetch import MarketFetcher
from app.data.rate_limiter import RateLimiter

ROOT = Path(__file__).resolve().parents[1]
LOG = ROOT / "data" / "tushare_snapshot.log"
EXTRA_DB = ROOT / "data" / "tushare_extra.db"
HISTORY_START = "20100104"


def log(msg: str):
    line = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}"
    print(line, flush=True)
    with open(LOG, "a") as f:
        f.write(line + "\n")


def _d(x: str) -> date:
    return date(int(x[:4]), int(x[4:6]), int(x[6:8]))


class Limited:
    """接口级限频 + 撞限自动等一分钟重试。"""
    def __init__(self, pro, per_min: int = 180):
        self.pro = pro
        self.limiters: dict[str, RateLimiter] = {}
        self.per_min = per_min
        import threading
        self._lock = threading.Lock()

    def call(self, name: str, **kw):
        lim = self.limiters.setdefault(name, RateLimiter(max_calls=self.per_min, period_s=60.0))
        for attempt in range(6):
            with self._lock:
                lim.acquire()
            try:
                return getattr(self.pro, name)(**kw)
            except Exception as exc:        # noqa: BLE001
                msg = str(exc)
                if "每分钟" in msg or "每小时" in msg or "频率" in msg:
                    log(f"  limit hit on {name}: {msg[:60]} → sleep 61s")
                    time.sleep(61)
                elif "权限" in msg:
                    raise
                else:
                    log(f"  {name} error attempt{attempt}: {msg[:80]}")
                    time.sleep(3 * (attempt + 1))
        raise RuntimeError(f"{name} failed repeatedly")


# ── 流 A:日线 ───────────────────────────────────────────────────────────
def phase_quotes(lim: Limited):
    s = get_settings()
    session = make_session_factory(make_engine())()
    pro = lim.pro

    class _L:                      # MarketFetcher 只要 acquire();限频由 Limited 做
        def acquire(self):
            pass

    class _Pro:                    # 把 MarketFetcher 的三个调用导到 Limited
        def daily(self, **kw): return lim.call("daily", **kw)
        def daily_basic(self, **kw): return lim.call("daily_basic", **kw)
        def adj_factor(self, **kw): return lim.call("adj_factor", **kw)
    fetcher = MarketFetcher(pro=_Pro(), limiter=_L())

    # 这台机的盘 fsync 慢(每天一次 commit 要好几秒):WAL + synchronous=NORMAL,10 天一提交
    session.execute(text("pragma synchronous=NORMAL"))

    def write_day(d: date, rows: list[dict], commit: bool):
        if rows:
            session.execute(insert(DailyQuote).prefix_with("OR REPLACE"), rows)
            session.merge(IngestedDay(trade_date=d))
        if commit:
            session.commit()

    have = set(session.scalars(select(DailyQuote.trade_date).distinct()).all())
    cal = lim.call("trade_cal", start_date=HISTORY_START, end_date="20260911", is_open="1")
    days = sorted(_d(str(x)) for x in cal["cal_date"])

    # 1) 2021~2023 缺口 + 2) 2026 量比为空的日子 + 3) 2010~2020 追溯,按优先级排
    gap = [d for d in days if date(2021, 1, 1) <= d <= date(2023, 6, 1) and d not in have]
    vr_null = session.execute(
        select(DailyQuote.trade_date, func.count()).where(
            DailyQuote.volume_ratio.is_(None), DailyQuote.trade_date >= date(2026, 1, 1),
            DailyQuote.trade_date < date(2026, 9, 14)).group_by(DailyQuote.trade_date)).all()
    refill = sorted(d for d, n in vr_null if n > 1000)
    hist = [d for d in days if d < date(2021, 1, 1) and d not in have]
    log(f"quotes: 缺口 {len(gap)} 天, 量比重刷 {len(refill)} 天, 2010~2020 追溯 {len(hist)} 天")
    t0 = time.time(); n = 0
    from concurrent.futures import ThreadPoolExecutor
    for label, todo in (("gap", gap), ("refill", refill), ("hist", hist)):
        # 3 个线程预取(tushare 单次 1~1.5s,接口限频仍由 Limited 统一控制),主线程顺序落库
        def safe_fetch(d):
            try:
                return fetcher.fetch_day(d)
            except Exception as exc:        # noqa: BLE001 — 单天失败记日志跳过,下次重跑再补
                log(f"  {label} {d} FAIL {str(exc)[:80]}")
                return None
        with ThreadPoolExecutor(max_workers=3) as ex:
            for d, rows in zip(todo, ex.map(safe_fetch, todo)):
                n += 1
                if rows is None:
                    continue
                write_day(d, rows, commit=(n % 10 == 0))
                if n % 20 == 0:
                    log(f"  {label} {d}: {len(rows)} rows  ({n} days, {time.time() - t0:.0f}s)")
        session.commit()
    log(f"quotes done: {n} days in {time.time() - t0:.0f}s")


# ── 流 B:其他数据集 → tushare_extra.db ───────────────────────────────────
def _extra():
    con = sqlite3.connect(EXTRA_DB, timeout=120)
    con.execute("pragma journal_mode=wal")
    con.execute("pragma synchronous=NORMAL")
    return con


def _save(con, table: str, df: pd.DataFrame):
    if df is None or df.empty:
        return 0
    df.to_sql(table, con, if_exists="append", index=False)
    return len(df)


def _done_codes(con, table: str) -> set:
    try:
        return {r[0] for r in con.execute(f"select distinct ts_code from {table}")}
    except sqlite3.OperationalError:
        return set()


def phase_extra(lim: Limited, only: list[str] | None = None):
    con = _extra()
    want = lambda k: not only or k in only

    if want("basic"):
        for tbl in ("ts_stock_basic", "ts_stock_company", "ts_trade_cal", "ts_index_daily", "ts_index_weight"):
            con.execute(f"drop table if exists {tbl}")
        fields = ("ts_code,symbol,name,area,industry,fullname,enname,cnspell,market,exchange,"
                  "curr_type,list_status,list_date,delist_date,is_hs,act_name,act_ent_type")
        for st in ("L", "D", "P"):
            n = _save(con, "ts_stock_basic", lim.call("stock_basic", exchange="", list_status=st, fields=fields))
            log(f"stock_basic {st}: {n}")
        for ex in ("SSE", "SZSE", "BSE"):
            log(f"stock_company {ex}: {_save(con, 'ts_stock_company', lim.call('stock_company', exchange=ex))}")
        log(f"trade_cal: {_save(con, 'ts_trade_cal', lim.call('trade_cal', start_date='19901201', end_date='20271231'))}")
        for idx in ("000001.SH", "399001.SZ", "399006.SZ", "000300.SH", "000905.SH", "000852.SH",
                    "000688.SH", "000016.SH", "399005.SZ", "000985.SH", "932000.CSI"):
            try:
                n = _save(con, "ts_index_daily", lim.call("index_daily", ts_code=idx, start_date="20050101", end_date="20260914"))
                log(f"index_daily {idx}: {n}")
            except Exception as exc:    # noqa: BLE001
                log(f"index_daily {idx} FAIL {str(exc)[:60]}")
        for idx in ("000300.SH", "000905.SH", "000852.SH", "000016.SH"):
            tot = 0
            for y in range(2010, 2027):
                tot += _save(con, "ts_index_weight", lim.call("index_weight", index_code=idx,
                                                              start_date=f"{y}0101", end_date=f"{y}1231"))
            log(f"index_weight {idx}: {tot}")
        con.commit()

    codes = [r[0] for r in con.execute("select ts_code from ts_stock_basic")] if want("basic") or only else None
    if codes is None:
        codes = [r[0] for r in con.execute("select ts_code from ts_stock_basic")]
    log(f"per-stock universe: {len(codes)} (含退市)")

    per_stock = [("fina", "ts_fina_indicator", "fina_indicator", {}),
                 ("income", "ts_income", "income", {}),
                 ("balance", "ts_balancesheet", "balancesheet", {}),
                 ("cashflow", "ts_cashflow", "cashflow", {}),
                 ("dividend", "ts_dividend", "dividend", {})]
    for key, tbl, api, kw in per_stock:
        if not want(key):
            continue
        done = _done_codes(con, tbl)
        todo = [c for c in codes if c not in done]
        log(f"{api}: 已有 {len(done)} 只, 待拉 {len(todo)}")
        t0 = time.time()

        def fetch(c):
            try:
                return c, lim.call(api, ts_code=c, **kw)
            except Exception as exc:    # noqa: BLE001
                log(f"  {api} {c} FAIL {str(exc)[:60]}")
                return c, None
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=4) as ex:      # 单次 1~2s,4 线程贴着限频跑
            for i, (c, df) in enumerate(ex.map(fetch, todo), 1):
                if df is None:
                    continue
                if df.empty:                # 记一行空标记,避免重跑时再拉
                    df = pd.DataFrame({"ts_code": [c]})
                _save(con, tbl, df)
                if i % 50 == 0:
                    con.commit()
                if i % 200 == 0:
                    log(f"  {api} {i}/{len(todo)} ({time.time() - t0:.0f}s)")
        con.commit()
        log(f"{api} done in {time.time() - t0:.0f}s")

    if want("moneyflow"):
        have = set()
        try:
            have = {r[0] for r in con.execute("select distinct trade_date from ts_moneyflow")}
        except sqlite3.OperationalError:
            pass
        cal = lim.call("trade_cal", start_date="20100104", end_date="20260914", is_open="1")
        days = [d for d in sorted(cal["cal_date"]) if d not in have]
        log(f"moneyflow: 待拉 {len(days)} 天")
        t0 = time.time()
        from concurrent.futures import ThreadPoolExecutor
        days = list(reversed(days))                     # 新的先拉
        with ThreadPoolExecutor(max_workers=3) as ex:
            for i, df in enumerate(ex.map(lambda d: lim.call("moneyflow", trade_date=d), days), 1):
                _save(con, "ts_moneyflow", df)
                if i % 50 == 0:
                    con.commit(); log(f"  moneyflow {i}/{len(days)} ({time.time() - t0:.0f}s)")
        con.commit()
        log("moneyflow done")
    con.close()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("stream", choices=["quotes", "extra"])
    p.add_argument("--only", nargs="*", help="extra 流只跑这些: basic fina income balance cashflow dividend moneyflow")
    p.add_argument("--per-min", type=int, default=180)
    a = p.parse_args()
    import tushare as ts
    lim = Limited(ts.pro_api(get_settings().tushare_token), per_min=a.per_min)
    if a.stream == "quotes":
        phase_quotes(lim)
    else:
        phase_extra(lim, a.only)


if __name__ == "__main__":
    main()
