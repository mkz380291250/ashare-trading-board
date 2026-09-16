"""多 regime 因子稳健性:逐日 RankIC → 按年/按 regime 聚合 → 全周期稳健判定。"""
import numpy as np
import pandas as pd

# (key, 标签, 起, 止) —— 连续覆盖 2011 起
REGIMES = [
    ("R1", "2011-14上半 震荡熊", "2011-01-01", "2014-06-30"),
    ("R2", "2014下-15上 杠杆牛", "2014-07-01", "2015-06-30"),
    ("R3", "2015下-16初 股灾", "2015-07-01", "2016-02-29"),
    ("R4", "2016-18 白马/去杠杆", "2016-03-01", "2018-12-31"),
    ("R5", "2019-21 成长牛", "2019-01-01", "2021-12-31"),
    ("R6", "2022-24.8 小盘红利熊", "2022-01-01", "2024-08-31"),
    ("R7", "2024.9- 924后", "2024-09-01", "2099-12-31"),
]

MARK_THR = 0.015


def daily_rank_ic(score: pd.Series, label: pd.Series) -> pd.Series:
    """逐日截面 Spearman;两者 index 都是 (datetime, instrument)。
    用组内 rank + Pearson 向量化,避免逐日 Python 循环。"""
    j = pd.DataFrame({"s": score, "y": label}).dropna()
    if j.empty:
        return pd.Series(dtype="float64")
    g = j.groupby(level="datetime")
    n = g.size()
    rs = g["s"].rank()
    ry = g["y"].rank()
    j = pd.DataFrame({"rs": rs, "ry": ry})
    g = j.groupby(level="datetime")
    ms, my = g["rs"].transform("mean"), g["ry"].transform("mean")
    ds, dy = j["rs"] - ms, j["ry"] - my
    num = (ds * dy).groupby(level="datetime").sum()
    den = np.sqrt((ds * ds).groupby(level="datetime").sum() * (dy * dy).groupby(level="datetime").sum())
    ric = (num / den.replace(0.0, np.nan))
    ric = ric[(n >= 5)].dropna()
    return ric.sort_index().astype("float64")


def _stats(s: pd.Series) -> dict:
    s = s.dropna()
    n = len(s)
    ic = float(s.mean()) if n else 0.0
    sd = float(s.std()) if n > 1 else 0.0
    ir = float(ic / sd) if sd else 0.0
    return {"ic": ic, "ir": ir, "days": int(n)}


def aggregate(ric: pd.Series, regimes=REGIMES) -> dict:
    idx = pd.DatetimeIndex(ric.index)
    out = {"overall": _stats(ric), "years": {}, "regimes": {}}
    last = idx.max() if len(idx) else pd.Timestamp("2000-01-01")
    out["recent3y"] = _stats(ric[idx >= last - pd.DateOffset(years=3)])
    for y, g in ric.groupby(idx.year):
        out["years"][str(y)] = _stats(g)
    for key, _label, s, e in regimes:
        m = (idx >= pd.Timestamp(s)) & (idx <= pd.Timestamp(e))
        if m.any():
            out["regimes"][key] = _stats(ric[m])
    return out


def robust_all_regimes(agg: dict, *, min_same_sign: int | None = None,
                       min_abs_ic: float = MARK_THR, min_hits: int | None = None) -> bool:
    """≥min_same_sign 个 regime 与全期同号,且 ≥min_hits 个 regime 同号且 |ic|≥min_abs_ic。
    缺省按"有数据的 regime 数 n"取 n−1 / n−2(7 段时即 6/5;截止 2021 只有 5 段时 4/3),
    这样 walk-forward 截断历史时门槛按比例收紧而不是无法满足。"""
    sign = np.sign(agg["overall"]["ic"]) or 1.0
    regs = [r for r in agg["regimes"].values() if r.get("days", 0) > 0]
    n = len(regs)
    if n == 0:
        return False
    if min_same_sign is None:
        min_same_sign = max(n - 1, 1)
    if min_hits is None:
        min_hits = max(n - 2, 1)
    same = sum(1 for r in regs if np.sign(r["ic"]) == sign)
    hits = sum(1 for r in regs if abs(r["ic"]) >= min_abs_ic and np.sign(r["ic"]) == sign)
    return same >= min_same_sign and hits >= min_hits


def mark(ic: float, thr: float = MARK_THR) -> str:
    return "+" if ic >= thr else ("−" if ic <= -thr else "0")


def render_md(rep: dict) -> str:
    keys = [k for k, *_ in rep["regimes"]]
    L = [f"# 因子多 regime 重检 {rep['as_of']}", "",
         f"- 宇宙 {rep['universe']} | h{rep['horizon']} | 起 {rep['start']} | "
         f"因子 {len(rep['factors'])} | 全周期稳健 {sum(f.get('robust_all') for f in rep['factors'])}",
         "- regime:" + " / ".join(f"{k}={lbl}({s}~{e})" for k, lbl, s, e in rep["regimes"]),
         f"- 方向标记:+ ≥+{MARK_THR},− ≤−{MARK_THR},0 介于其间,· 无数据;"
         "★=全周期稳健(≥6/7 段与全期同号,且 ≥5 段同号 |IC|≥0.015);✓=当前 frozen"]
    if rep.get("skipped"):
        L.append(f"- 跳过(研究库缺字段):{rep['skipped']}")
    L.append("")
    fams: dict = {}
    for f in rep["factors"]:
        fams.setdefault(f.get("family", "其他"), []).append(f)
    for fam, fs in fams.items():
        L.append(f"## {fam}")
        L.append("| 因子 | frozen | 全期IC/IR | 近3年IC | " + " | ".join(keys) + " | 稳健 |")
        L.append("|---|---|---|---|" + "---|" * len(keys) + "---|")
        for f in sorted(fs, key=lambda x: -abs(x["agg"]["overall"]["ir"])):
            a = f["agg"]
            marks = " | ".join(mark(a["regimes"][k]["ic"]) if k in a["regimes"] else "·"
                               for k in keys)
            L.append(f"| {f['name']} | {'✓' if f.get('in_frozen') else ''} | "
                     f"{a['overall']['ic']:+.3f}/{a['overall']['ir']:+.2f} | "
                     f"{a['recent3y']['ic']:+.3f} | {marks} | {'★' if f.get('robust_all') else ''} |")
        L.append("")
    return "\n".join(L)
