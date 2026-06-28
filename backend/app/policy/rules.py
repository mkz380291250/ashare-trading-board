"""策略闸检测函数(纯读、无副作用):因子衰减 / 风控停买 / 弱持仓。
供 step_debate 即时行动与 step_policy 审计。"""
from datetime import date
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.db.models import FactorICDaily
from app.attribution.forward_ic import latest_rolling_rank_ic


def factor_decayed(session: Session, as_of: date, *, window: int = 20,
                   consecutive: int = 5, threshold: float = 0.02) -> bool:
    days = session.scalars(select(FactorICDaily.as_of).where(
        FactorICDaily.as_of <= as_of).order_by(
        FactorICDaily.as_of.desc()).limit(consecutive)).all()
    if len(days) < consecutive:
        return False
    for d in days:
        ric = latest_rolling_rank_ic(session, as_of=d, window=window)
        if ric is None or ric >= threshold:
            return False
    return True
