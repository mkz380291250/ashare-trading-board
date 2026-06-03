import pandas as pd
from app.backtest.symbols import to_qlib_symbol


def build_score_frame(dates, factor_fn, scorer) -> pd.DataFrame:
    """对每个交易日用 factor_fn 取因子、scorer.score_all 全市场打分,
    汇成 MultiIndex (datetime, instrument) 单列 'score' 的 DataFrame。
    factor_fn(d) 返回 {factor: {code: value}};返回 {} 的日子跳过。"""
    rows = []
    for d in dates:
        factors = factor_fn(d)
        if not factors:
            continue
        for code, total, _raw in scorer.score_all(factors):
            rows.append((pd.Timestamp(d), to_qlib_symbol(code), total))
    idx = pd.MultiIndex.from_tuples(
        [(r[0], r[1]) for r in rows] or [],
        names=["datetime", "instrument"])
    return pd.DataFrame({"score": [r[2] for r in rows]}, index=idx)
