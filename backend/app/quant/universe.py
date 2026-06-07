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
