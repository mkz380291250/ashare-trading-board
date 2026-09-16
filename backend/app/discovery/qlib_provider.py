"""qlib 复合因子选股:加载冻结产物,对全市场打分取最新交易日截面排序。
纯逻辑(score_panel/latest_section)不依赖 qlib;qlib 取数在 load_features 里。"""
import json
from datetime import date
import pandas as pd
from sqlalchemy import delete
from sqlalchemy.orm import Session
from app.quant.factor_compose import composite_score
from app.db.models import DiscoveryPick
from app.factors.frozen import FrozenFactors
from app.quant.factor_mine import FACTOR_LIBRARY, to_datetime_instrument
from app.backtest.symbols import from_qlib_symbol


def score_panel(panel: pd.DataFrame, signs: dict,
                weights: dict | None = None) -> pd.DataFrame:
    """panel: MultiIndex(datetime,instrument) 因子面板 -> 单列 'score'。"""
    return composite_score(panel, signs, weights=weights)


def latest_section(score_df: pd.DataFrame) -> pd.Series:
    """取最新 datetime 截面,返回 index=instrument 的降序 Series。"""
    if score_df.empty:
        return pd.Series(dtype=float, name="score")
    last = score_df.index.get_level_values("datetime").max()
    sec = score_df.xs(last, level="datetime")["score"]
    return sec.sort_values(ascending=False)


def load_features(insts: list[str], factors: list[str], as_of: date,
                  lookback: int) -> pd.DataFrame:
    """qlib D.features 薄包装:按 as_of 回溯 lookback 交易日取数,
    返回列名=因子名的面板。需先 init_qlib()。"""
    from qlib.data import D
    cal = [c.date() for c in D.calendar(end_time=as_of)]
    start = cal[-lookback] if len(cal) >= lookback else cal[0]
    end = cal[-1]
    fields = [FACTOR_LIBRARY[n] for n in factors]
    df = D.features(insts, fields, start_time=start, end_time=end)
    df.columns = factors
    return to_datetime_instrument(df)


def run_qlib_discovery(session: Session, as_of: date, frozen: FrozenFactors,
                       insts: list[str], *, lookback: int = 60,
                       load_features_fn=load_features) -> list[tuple[str, float]]:
    """对全市场用冻结因子打分,取最新截面降序,全量覆盖写 DiscoveryPick。"""
    panel = load_features_fn(insts, frozen.factors, as_of, lookback)
    score_df = score_panel(panel, frozen.signs, frozen.weights)
    section = latest_section(score_df)
    ranked = [(from_qlib_symbol(str(code)), float(sc)) for code, sc in section.items()]
    session.execute(delete(DiscoveryPick).where(DiscoveryPick.as_of == as_of))
    for i, (code, sc) in enumerate(ranked, 1):
        session.add(DiscoveryPick(as_of=as_of, code=code, rank=i, score=sc,
                                  factors=json.dumps({"composite": sc})))
    session.commit()
    return ranked
