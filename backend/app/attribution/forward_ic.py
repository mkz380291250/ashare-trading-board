# backend/app/attribution/forward_ic.py
"""复合因子每日前向 IC:对 DiscoveryPick 某日的 score 截面 vs 各 code horizon 日前向收益,
算 IC(Pearson)/RankIC(Spearman),一行一 as_of,按 as_of upsert,回填幂等。"""
from datetime import date, timedelta
import pandas as pd
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from app.db.models import DiscoveryPick, FactorICDaily


def daily_ic(pairs: list[tuple[float, float]]) -> tuple[float | None, float | None, int]:
    df = pd.DataFrame(pairs, columns=["score", "ret"]).dropna()
    n = len(df)
    if n < 2 or df["score"].nunique() < 2 or df["ret"].nunique() < 2:
        return (None, None, n)
    ic = float(df["score"].corr(df["ret"]))
    ric = float(df["score"].corr(df["ret"], method="spearman"))
    return (ic, ric, n)


def _fwd_return(store, code: str, pick_date: date, horizon: int) -> float | None:
    bars = store.get_bars(code, pick_date, pick_date + timedelta(days=horizon * 4 + 10))
    closes = [b.close for b in bars if b.trade_date >= pick_date]
    if len(closes) <= horizon or closes[0] == 0:
        return None
    return closes[horizon] / closes[0] - 1.0


def backfill_factor_ic(session: Session, store, as_of: date, *, horizon: int = 5,
                       lookback_days: int = 30) -> int:
    start = as_of - timedelta(days=lookback_days)
    pick_dates = session.scalars(select(DiscoveryPick.as_of).where(
        DiscoveryPick.as_of >= start, DiscoveryPick.as_of <= as_of).distinct()).all()
    count = 0
    for pdate in sorted(set(pick_dates)):       # 不要用 pd:会遮蔽 pandas 别名
        picks = session.scalars(select(DiscoveryPick).where(
            DiscoveryPick.as_of == pdate)).all()
        pairs = []
        for p in picks:
            r = _fwd_return(store, p.code, pdate, horizon)
            if r is not None:
                pairs.append((p.score, r))
        if len(pairs) < 2:
            continue                       # 前向窗口未走完 / 数据不足,暂不写
        ic, ric, n = daily_ic(pairs)
        row = session.get(FactorICDaily, pdate)
        if row is None:
            row = FactorICDaily(as_of=pdate)
            session.add(row)
        row.ic, row.rank_ic, row.n = ic, ric, n
        count += 1
    session.commit()
    return count


def latest_rolling_rank_ic(session: Session, *, as_of: date,
                           window: int = 20) -> float | None:
    rows = session.scalars(select(FactorICDaily).where(
        FactorICDaily.as_of <= as_of).order_by(
        FactorICDaily.as_of.desc()).limit(window)).all()
    vals = [r.rank_ic for r in rows if r.rank_ic is not None]
    return (sum(vals) / len(vals)) if vals else None
