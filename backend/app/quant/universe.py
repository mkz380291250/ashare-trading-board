"""投资域(universe)构建:全市场剔除 ST / 次新,产出 qlib instruments 文件。"""
from datetime import date
from pathlib import Path
from app.backtest.symbols import to_qlib_symbol


def filter_investable(rows, as_of: date, min_list_days: int = 120) -> list[str]:
    """从 (code, name, list_date) 行中筛出可投资标的。

    剔除:名称含 'ST'(含 *ST)的;上市不足 min_list_days 个自然日的次新;
    缺 list_date 的。保留顺序与输入一致。

    局限:ST 判定基于当前名称,非时点(历史摘帽票会被当前状态误判)。
    """
    out = []
    for code, name, list_date in rows:
        if name and "ST" in name.upper():
            continue
        if list_date is None:
            continue
        if (as_of - list_date).days < min_list_days:
            continue
        out.append(code)
    return out


def write_instruments(codes, path: str, *, start: date, end: date) -> int:
    """写 qlib instruments 文件:每行 `SYMBOL\\tSTART\\tEND`(日期 YYYY-MM-DD)。
    返回写出的行数。"""
    s, e = start.isoformat(), end.isoformat()
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"{to_qlib_symbol(c)}\t{s}\t{e}" for c in codes]
    p.write_text("\n".join(lines) + ("\n" if lines else ""))
    return len(lines)


def dynamic_rows(rows, *, cal_start: date, cal_end: date, min_list_days: int = 120,
                 prefixes: tuple = ("300", "301")) -> list[tuple[str, date, date]]:
    """按票给出动态起止日(供 qlib instruments 每行 SYMBOL START END):
    start = max(list_date + min_list_days, cal_start);end = delist_date−1 或 cal_end。
    只保留代码前缀在 prefixes 的票(空元组=不限);仍按当前名称剔 ST(已知局限)。
    start > end(次新或早退市)的票丢弃。rows 元素 (code, name, list_date, delist_date|None)。"""
    from datetime import timedelta
    out = []
    for code, name, list_date, delist_date in rows:
        if prefixes and not code.split(".")[0].startswith(tuple(prefixes)):
            continue
        if name and "ST" in name.upper():
            continue
        if list_date is None:
            continue
        start = max(list_date + timedelta(days=min_list_days), cal_start)
        end = min(delist_date - timedelta(days=1), cal_end) if delist_date else cal_end
        if start > end:
            continue
        out.append((code, start, end))
    return out


def write_instrument_rows(rows3, path) -> int:
    """写 qlib instruments:每行 `SYMBOL\\tSTART\\tEND`。返回行数。"""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"{to_qlib_symbol(c)}\t{s.isoformat()}\t{e.isoformat()}" for c, s, e in rows3]
    p.write_text("\n".join(lines) + ("\n" if lines else ""))
    return len(lines)


def basic_from_extra_db(db_path: str) -> list[tuple]:
    """tushare_extra.db.ts_stock_basic → [(code, name, list_date, delist_date|None)],含已退市。"""
    import sqlite3
    from datetime import datetime

    def _d(s):
        return datetime.strptime(s, "%Y%m%d").date() if s else None

    con = sqlite3.connect(db_path)
    try:
        cur = con.execute("select ts_code,name,list_date,delist_date from ts_stock_basic")
        return [(code, name, _d(ld), _d(dd)) for code, name, ld, dd in cur]
    finally:
        con.close()


def index_member_rows(snapshots, *, cal_end: date) -> list[tuple[str, date, date]]:
    """月度成分快照 → 每只票的连续成员区间(供 qlib instruments 多行同票)。
    snapshots: [(trade_date 'YYYYMMDD', con_code)],某快照日在册即视为从该日起到下一快照日前一天在册;
    最后一次快照延续到 cal_end。相邻区间合并。"""
    from datetime import datetime, timedelta
    by_date: dict[str, set] = {}
    for d, c in snapshots:
        by_date.setdefault(d, set()).add(c)
    days = sorted(by_date)
    parse = lambda s: datetime.strptime(s, "%Y%m%d").date()   # noqa: E731
    spans: dict[str, list] = {}
    for i, d in enumerate(days):
        start = parse(d)
        end = parse(days[i + 1]) - timedelta(days=1) if i + 1 < len(days) else cal_end
        for c in by_date[d]:
            lst = spans.setdefault(c, [])
            if lst and lst[-1][1] + timedelta(days=1) == start:
                lst[-1][1] = end                       # 连续 → 合并
            else:
                lst.append([start, end])
    out = []
    for c in sorted(spans):
        for s, e in spans[c]:
            if s <= e:
                out.append((c, s, e))
    return out


def index_snapshots_from_extra_db(db_path: str, index_code: str) -> list[tuple[str, str]]:
    import sqlite3
    con = sqlite3.connect(db_path)
    try:
        return con.execute("select trade_date, con_code from ts_index_weight where index_code=?",
                           (index_code,)).fetchall()
    finally:
        con.close()
