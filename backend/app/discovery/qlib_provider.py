"""qlib 复合因子选股:加载冻结产物,对全市场打分取最新交易日截面排序。
纯逻辑(score_panel/latest_section)不依赖 qlib;qlib 取数在 score_universe 里。"""
import pandas as pd
from app.quant.factor_compose import composite_score


def score_panel(panel: pd.DataFrame, signs: dict) -> pd.DataFrame:
    """panel: MultiIndex(datetime,instrument) 因子面板 -> 单列 'score'。"""
    return composite_score(panel, signs)


def latest_section(score_df: pd.DataFrame) -> pd.Series:
    """取最新 datetime 截面,返回 index=instrument 的降序 Series。"""
    last = score_df.index.get_level_values("datetime").max()
    sec = score_df.xs(last, level="datetime")["score"]
    return sec.sort_values(ascending=False)
