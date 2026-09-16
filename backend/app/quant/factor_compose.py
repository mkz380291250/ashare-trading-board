"""复合因子:把稳健的单因子(按符号校正、相关性/族限量去重)等权或 IR 加权合成一个打分。

合成约定:每个因子按日截面 z-score,再乘符号(反向因子取负),使「越大越好」;
对去重后的因子取等权均值得到 composite score,接 TopkDropout 回测。
"""
import pandas as pd
from app.quant.ml_pipeline import cs_zscore


def sign_correct(ic) -> float:
    """按 RankIC 方向给符号:>=0 取 +1(正向),<0 取 -1(反向因子取负)。"""
    return -1.0 if (ic is not None and ic < 0) else 1.0


def dedup_by_correlation(ranked: list[str], corr: pd.DataFrame,
                         threshold: float = 0.8) -> list[str]:
    """按 ranked 顺序贪心保留:与已保留因子 |相关| 均 < threshold 才留下。
    ranked 应按重要性(|IR|)降序,故保留的是更强者。"""
    kept: list[str] = []
    for f in ranked:
        if all(abs(corr.loc[f, k]) < threshold for k in kept):
            kept.append(f)
    return kept


def dedup_by_family(ranked: list[str], corr: pd.DataFrame, family: dict,
                    *, threshold: float = 0.7, family_cap: int = 2) -> list[str]:
    """按 ranked 顺序贪心:同族最多 family_cap 个,且与已留因子 |corr| 均 < threshold。"""
    kept: list[str] = []
    count: dict[str, int] = {}
    for f in ranked:
        fam = family.get(f, "其他")
        if count.get(fam, 0) >= family_cap:
            continue
        if all(abs(corr.loc[f, k]) < threshold for k in kept):
            kept.append(f)
            count[fam] = count.get(fam, 0) + 1
    return kept


def ir_weights(kept: list[str], ir_map: dict, *, lo: float = 0.5, hi: float = 2.0) -> dict:
    """|IR| 截断在 [lo×均值, hi×均值] 后归一(和为 1);缺 IR 的按均值计。"""
    if not kept:
        return {}
    raw = {f: abs(ir_map.get(f) or 0.0) for f in kept}
    mean = sum(raw.values()) / len(raw) or 1.0
    clipped = {f: min(max(v if v > 0 else mean, lo * mean), hi * mean) for f, v in raw.items()}
    tot = sum(clipped.values())
    return {f: round(v / tot, 6) for f, v in clipped.items()}


def composite_score(panel: pd.DataFrame, signs: dict,
                    weights: dict | None = None) -> pd.DataFrame:
    """panel: MultiIndex(datetime,instrument) 的因子面板;signs: {因子:±1};
    weights: {因子:权重}(缺省等权;给了则按权重归一后加权)。
    返回单列 'score' 的 DataFrame(每日截面 z-score×符号后跨因子(加权)平均)。"""
    cols = [c for c in panel.columns if c in signs]
    if weights:
        w = {c: float(weights.get(c) or 0.0) for c in cols}
        tot = sum(w.values())
        if tot > 0:
            parts = [cs_zscore(panel[c]) * signs[c] * (w[c] / tot) for c in cols]
            return pd.DataFrame({"score": pd.concat(parts, axis=1).sum(axis=1)})
    parts = [cs_zscore(panel[c]) * signs[c] for c in cols]
    score = pd.concat(parts, axis=1).mean(axis=1)
    return pd.DataFrame({"score": score})
