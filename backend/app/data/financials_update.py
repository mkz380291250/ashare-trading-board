"""财务续接:tushare 到期后用 baostock 季报把营收/归母净利追加进 tushare_extra.db 的
ts_income(只补库里没有的报告期,历史行仍是 tushare 原值)。供 PIT 字段 rev_ttm/np_ttm
(sp_ttm/ep_ttm 因子)在生产库里持续可算。

口径差异(2026-09-16 宁德时代 2026H1 实测):baostock MBRevenue 与 tushare revenue
完全一致;baostock netProfit 是含少数股东的净利润,比 tushare 归母净利高约 9%,
所以续接后 rev_ttm/sp_ttm 严格连续,np_ttm 在新季度略偏高(生产 frozen 只用 sp_ttm)。"""
import sqlite3
from datetime import date

import pandas as pd

INCOME_COLS = ("ts_code", "ann_date", "f_ann_date", "end_date", "report_type",
               "revenue", "n_income_attr_p")


def _ymd(s) -> str:
    """'2026-10-25' / '20261025' → '20261025';空 → ''。"""
    s = "" if s is None else str(s).strip()
    return s.replace("-", "") if s else ""


def _f(v):
    try:
        return float(v) if v not in (None, "") and not pd.isna(v) else None
    except (TypeError, ValueError):
        return None


def profit_rows(df: pd.DataFrame | None, ts_code: str) -> list[dict]:
    """baostock query_profit_data 结果 → 待插入行。缺公告日/报告期/营收的跳过。"""
    if df is None or df.empty:
        return []
    out = []
    for _, r in df.iterrows():
        ann, end = _ymd(r.get("pubDate")), _ymd(r.get("statDate"))
        rev, np_ = _f(r.get("MBRevenue")), _f(r.get("netProfit"))
        if not ann or not end or rev is None:
            continue
        out.append({"ts_code": ts_code, "ann_date": ann, "end_date": end,
                    "revenue": rev, "n_income_attr_p": np_})
    return out


def _has(con, ts_code: str, end_date: str) -> bool:
    return con.execute("select 1 from ts_income where ts_code=? and end_date=? limit 1",
                       (ts_code, end_date)).fetchone() is not None


def upsert_income(con: sqlite3.Connection, rows: list[dict]) -> int:
    """只插入 (ts_code, end_date) 尚不存在的行;report_type 固定 '1'(合并报表)。返回插入数。"""
    n = 0
    for r in rows:
        if _has(con, r["ts_code"], r["end_date"]):
            continue
        con.execute(
            "insert into ts_income (ts_code, ann_date, f_ann_date, end_date, report_type, "
            "revenue, n_income_attr_p) values (?,?,?,?,?,?,?)",
            (r["ts_code"], r["ann_date"], r["ann_date"], r["end_date"], "1",
             r["revenue"], r["n_income_attr_p"]))
        n += 1
    con.commit()
    return n


def recent_quarters(today: date, n: int) -> list[tuple[int, int]]:
    """从今天往前数 n 个「可能已披露」的报告期 (year, quarter),最近在前(当季未披露)。"""
    y, q = today.year, (today.month - 1) // 3
    out = []
    for _ in range(n):
        if q == 0:
            y, q = y - 1, 4
        out.append((y, q))
        q -= 1
    return out


def _end_of(y: int, q: int) -> str:
    return f"{y}{('0331', '0630', '0930', '1231')[q - 1]}"


def pending_quarters(con, ts_code: str, today: date, n: int = 2) -> list[tuple[int, int]]:
    """最近 n 个可能已披露的报告期里,库中尚无该票记录的。"""
    return [(y, q) for y, q in recent_quarters(today, n) if not _has(con, ts_code, _end_of(y, q))]


def update_financials(db_path: str, codes, *, fetch_fn, today: date | None = None,
                      n: int = 2, log=None) -> dict:
    """对每只票查缺失的最近 n 个报告期,fetch_fn(ts_code, year, quarter) → DataFrame
    (baostock query_profit_data 口径),插入新行。返回统计。单表失败计入 errors 不中断。"""
    today = today or date.today()
    con = sqlite3.connect(db_path)
    stats = {"codes": 0, "queries": 0, "inserted": 0, "errors": 0}
    try:
        for i, code in enumerate(codes):
            stats["codes"] += 1
            for y, q in pending_quarters(con, code, today, n):
                stats["queries"] += 1
                try:
                    df = fetch_fn(code, y, q)
                except Exception as exc:        # noqa: BLE001 — 单票失败不阻断
                    stats["errors"] += 1
                    if log:
                        log(f"  {code} {y}Q{q} 失败: {exc!r}")
                    continue
                stats["inserted"] += upsert_income(con, profit_rows(df, code))
            if log and (i + 1) % 500 == 0:
                log(f"  financials {i + 1}/{len(codes)} queries={stats['queries']} "
                    f"inserted={stats['inserted']}")
    finally:
        con.close()
    return stats


def baostock_fetch_fn(src=None):
    """返回 fetch_fn(ts_code, year, quarter),复用单会话 BaostockSource。"""
    from app.data.baostock_source import BaostockSource, to_bs_code
    src = src or BaostockSource()

    def fetch(ts_code: str, year: int, quarter: int) -> pd.DataFrame:
        src._ensure_login()
        return src._query(src.bs.query_profit_data(code=to_bs_code(ts_code),
                                                    year=year, quarter=quarter))
    return fetch, src
