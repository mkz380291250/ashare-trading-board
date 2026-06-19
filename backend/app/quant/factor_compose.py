"""复合因子:把稳健的单因子(按符号校正、相关性去重)等权合成一个打分。

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


def composite_score(panel: pd.DataFrame, signs: dict) -> pd.DataFrame:
    """panel: MultiIndex(datetime,instrument) 的因子面板;signs: {因子:±1}。
    返回单列 'score' 的 DataFrame(每日截面 z-score×符号后跨因子等权)。"""
    cols = [c for c in panel.columns if c in signs]
    parts = [cs_zscore(panel[c]) * signs[c] for c in cols]
    score = pd.concat(parts, axis=1).mean(axis=1)
    return pd.DataFrame({"score": score})
