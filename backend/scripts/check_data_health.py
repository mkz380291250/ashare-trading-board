"""数据健康检查:daily_quotes(sqlite)+ qlib bin 库。
用法: .venv/bin/python scripts/check_data_health.py [--days 10] [--sample 30] [--json]
退出码 0=PASS(允许 WARN),1=FAIL。夜链在 qlib 重建后也会调一次(daily_full step "health")。

检查项
  DB  最新交易日是否等于日历上最近一个已收盘交易日;最近 N 个交易日有无缺天
      最新一天行数是否明显低于近 20 日中位数(<80% → WARN,<50% → FAIL)
      最新一天关键字段空值率(close/vol/adj_factor 空 → FAIL;turnover/circ_mv/pb 空>5% → WARN)
      价格合理性:high<low / close 不在 [low,high] / 价格<=0
      复权因子:相邻两日因子比值 >1.5 或 <0.5 的股票数(除权不会这么大 → WARN)
  QLIB 日历最后一天 == DB 最新交易日;instruments/features 数;抽样 N 只:
      qlib $close×$factor 与 DB close×adj_factor 的最新一天是否一致(相对差 >1e-6 → FAIL)
"""
import argparse
import json
import statistics
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select, func, text

from app.config import get_settings
from app.db.database import make_engine, make_session_factory
from app.db.models import DailyQuote
from app.backtest.symbols import to_qlib_symbol


class Report:
    def __init__(self):
        self.items: list[dict] = []

    def add(self, level: str, name: str, msg: str):
        self.items.append({"level": level, "check": name, "msg": msg})

    ok = lambda self, n, m: self.add("PASS", n, m)          # noqa: E731
    warn = lambda self, n, m: self.add("WARN", n, m)        # noqa: E731
    fail = lambda self, n, m: self.add("FAIL", n, m)        # noqa: E731

    @property
    def failed(self):
        return any(i["level"] == "FAIL" for i in self.items)


def _trading_days_until_today(lookback_days: int) -> list[date]:
    """最近的交易日历:优先 baostock,失败退化成工作日。只算到"已收盘"的那天。"""
    from app.data.baostock_market import _after_close
    end = date.today() if _after_close() else date.today() - timedelta(days=1)
    start = end - timedelta(days=lookback_days)
    try:
        from app.data.baostock_source import BaostockSource
        src = BaostockSource()
        try:
            return src.trading_days(start, end)
        finally:
            src.close()
    except Exception:       # noqa: BLE001
        return [start + timedelta(days=i) for i in range((end - start).days + 1)
                if (start + timedelta(days=i)).weekday() < 5]


def check_db(session, rep: Report, days: int) -> tuple[date | None, list]:
    last = session.scalar(select(func.max(DailyQuote.trade_date)))
    if last is None:
        rep.fail("db.latest", "daily_quotes 为空")
        return None, []
    cal = _trading_days_until_today(days * 2 + 10)
    expected = cal[-1] if cal else None
    behind = [d for d in cal if d > last]
    if not behind:
        rep.ok("db.latest", f"最新交易日 {last}")
    elif behind == [date.today()]:
        rep.ok("db.latest", f"最新交易日 {last};今天 {behind[0]} 的等 22:00 夜链")
    else:
        rep.fail("db.latest", f"最新交易日 {last},日历上应到 {expected}(缺 {len(behind)} 天: {behind[:5]})")

    recent = [d for d in cal if d <= last][-days:]
    have = set(session.scalars(select(DailyQuote.trade_date).where(
        DailyQuote.trade_date >= (recent[0] if recent else last)).distinct()).all())
    missing = [d for d in recent if d not in have]
    if missing:
        rep.fail("db.gaps", f"最近 {days} 个交易日缺 {len(missing)} 天: {missing}")
    else:
        rep.ok("db.gaps", f"最近 {len(recent)} 个交易日无缺天")

    counts = session.execute(
        select(DailyQuote.trade_date, func.count()).where(DailyQuote.trade_date <= last)
        .group_by(DailyQuote.trade_date).order_by(DailyQuote.trade_date.desc()).limit(21)).all()
    n_last = counts[0][1]
    med = statistics.median([c for _, c in counts[1:]]) if len(counts) > 1 else n_last
    ratio = n_last / med if med else 1
    msg = f"{last} 有 {n_last} 行,近 20 日中位 {med:.0f}"
    if ratio < 0.5:
        rep.fail("db.rows", msg)
    elif ratio < 0.8:
        rep.warn("db.rows", msg)
    else:
        rep.ok("db.rows", msg)

    nulls = session.execute(text("""
        select count(*),
               sum(close is null or vol is null or adj_factor is null),
               sum(turnover_rate is null), sum(circ_mv is null), sum(pb is null), sum(amount is null)
        from daily_quotes where trade_date = :d"""), {"d": last}).one()
    n, hard, t_null, mv_null, pb_null, amt_null = nulls
    if hard:
        rep.fail("db.nulls", f"{last} 有 {hard} 行 close/vol/adj_factor 为空")
    soft = {"turnover_rate": t_null, "circ_mv": mv_null, "pb": pb_null, "amount": amt_null}
    bad = {k: v for k, v in soft.items() if n and v / n > 0.05}
    if bad:
        rep.warn("db.nulls", f"{last} 空值率>5%: " + ", ".join(f"{k}={v}/{n}" for k, v in bad.items()))
    elif not hard:
        rep.ok("db.nulls", f"{last} 关键字段无空值,软字段空值 {soft}")

    px = session.execute(text("""
        select sum(high < low), sum(close > high or close < low), sum(close <= 0 or open <= 0)
        from daily_quotes where trade_date = :d"""), {"d": last}).one()
    if any(px):
        rep.fail("db.prices", f"{last} 价格异常: high<low {px[0]}, close 出界 {px[1]}, 非正 {px[2]}")
    else:
        rep.ok("db.prices", f"{last} 价格关系正常")

    prev = [d for d in have if d < last]
    if prev:
        p = max(prev)
        jumps = session.execute(text("""
            select a.code, a.adj_factor, b.adj_factor from daily_quotes a join daily_quotes b
              on a.code = b.code and b.trade_date = :p
            where a.trade_date = :d and (a.adj_factor / b.adj_factor > 1.5 or a.adj_factor / b.adj_factor < 0.5)"""),
            {"d": last, "p": p}).all()
        changed = session.execute(text("""
            select count(*) from daily_quotes a join daily_quotes b
              on a.code = b.code and b.trade_date = :p
            where a.trade_date = :d and abs(a.adj_factor - b.adj_factor) > 1e-9"""), {"d": last, "p": p}).scalar()
        if jumps:
            rep.warn("db.factor", f"{p}→{last} 因子跳变>50% 的股票 {len(jumps)}: {[j[0] for j in jumps[:5]]}")
        else:
            rep.ok("db.factor", f"{p}→{last} 因子变化 {changed} 只(除权),无异常跳变")
    return last, recent


def check_qlib(session, rep: Report, last: date | None, sample: int):
    s = get_settings()
    qdir = Path(s.qlib_data_dir)
    cal_file = qdir / "calendars" / "day.txt"
    if not cal_file.exists():
        rep.fail("qlib.calendar", f"{cal_file} 不存在")
        return
    cal = cal_file.read_text().split()
    qlast = date.fromisoformat(cal[-1])
    if last and qlast < last:
        rep.fail("qlib.calendar", f"qlib 日历最后一天 {qlast} 落后 DB {last}(qlib 未重建)")
    else:
        rep.ok("qlib.calendar", f"qlib 日历 {cal[0]}..{cal[-1]},{len(cal)} 天")
    feats = qdir / "features"
    n_feat = sum(1 for _ in feats.iterdir()) if feats.exists() else 0
    inst = {p.stem: sum(1 for ln in p.read_text().splitlines() if ln.strip())
            for p in (qdir / "instruments").glob("*.txt")}
    rep.ok("qlib.instruments", f"features {n_feat} 只;instruments {inst}")
    for name in ("all", s.discovery_universe):
        if inst.get(name, 0) == 0:
            rep.fail("qlib.instruments", f"instruments/{name}.txt 为空或缺失")

    if not last:
        return
    try:
        from app.backtest.qlib_data import init_qlib
        init_qlib(str(qdir))
        from qlib.data import D
    except Exception as exc:        # noqa: BLE001
        rep.fail("qlib.init", f"qlib 初始化失败: {exc!r}")
        return
    rows = session.execute(
        select(DailyQuote.code, DailyQuote.close, DailyQuote.adj_factor, DailyQuote.vol)
        .where(DailyQuote.trade_date == last).order_by(DailyQuote.code)).all()
    step = max(1, len(rows) // sample)
    picked = rows[::step][:sample]
    syms = [to_qlib_symbol(r[0]) for r in picked]
    try:
        df = D.features(syms, ["$close", "$factor", "$volume"], start_time=str(last), end_time=str(last))
    except Exception as exc:        # noqa: BLE001
        rep.fail("qlib.features", f"读取 {last} 特征失败: {exc!r}")
        return
    if df.empty:
        rep.fail("qlib.features", f"qlib 里 {last} 没有任何数据")
        return
    bad, missing = [], []
    for (code, close, f, vol), sym in zip(picked, syms):
        try:
            r = df.loc[(sym, str(last))] if (sym, df.index.get_level_values(1)[0]) in df.index else None
        except Exception:       # noqa: BLE001
            r = None
        if r is None:
            sub = df.xs(sym, level=0, drop_level=True) if sym in df.index.get_level_values(0) else None
            if sub is None or sub.empty:
                missing.append(code)
                continue
            r = sub.iloc[-1]
        q_adj = float(r["$close"]) * float(r["$factor"])
        d_adj = close * f
        if d_adj and abs(q_adj / d_adj - 1) > 1e-6:
            bad.append((code, round(q_adj, 4), round(d_adj, 4)))
    if missing:
        rep.fail("qlib.features", f"抽样 {len(picked)} 只,qlib 缺 {len(missing)}: {missing[:5]}")
    if bad:
        rep.fail("qlib.features", f"复权价与 DB 不一致 {len(bad)} 只: {bad[:3]}")
    if not missing and not bad:
        rep.ok("qlib.features", f"抽样 {len(picked)} 只 {last} 复权价与 DB 一致")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--days", type=int, default=10)
    p.add_argument("--sample", type=int, default=30)
    p.add_argument("--json", action="store_true")
    p.add_argument("--skip-qlib", action="store_true")
    a = p.parse_args()
    rep = Report()
    session = make_session_factory(make_engine())()
    last, _ = check_db(session, rep, a.days)
    if not a.skip_qlib:
        check_qlib(session, rep, last, a.sample)
    if a.json:
        print(json.dumps(rep.items, ensure_ascii=False, indent=1))
    else:
        for i in rep.items:
            print(f"[{i['level']:4s}] {i['check']:16s} {i['msg']}")
        print("HEALTH_FAIL" if rep.failed else "HEALTH_OK", flush=True)
    return 1 if rep.failed else 0


if __name__ == "__main__":
    sys.exit(main())
