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


from app.db.models import EquitySnapshot, DiscoveryPick
from app.attribution.equity import current_drawdown
from app.attribution.outcomes import hit_rate


def is_risk_off(session: Session, as_of: date, *, account_id: int = 1,
                dd_stop: float = 0.20, hitrate_stop: float = 0.40,
                hit_window: int = 30) -> tuple[bool, str]:
    totals = session.scalars(select(EquitySnapshot.total).where(
        EquitySnapshot.account_id == account_id,
        EquitySnapshot.as_of <= as_of).order_by(EquitySnapshot.as_of)).all()
    dd = current_drawdown(list(totals))
    if dd is not None and dd < -dd_stop:
        return (True, f"回撤 {dd*100:.1f}% 破 {-dd_stop*100:.0f}%")
    hr = hit_rate(session, window=hit_window, as_of=as_of)
    if hr is not None and hr < hitrate_stop:
        return (True, f"胜率 {hr*100:.0f}% 破 {hitrate_stop*100:.0f}%")
    return (False, "")


def weak_holdings(session: Session, held: set[str], as_of: date, *,
                  pctl: float = 0.50, consecutive: int = 3) -> list[str]:
    days = session.scalars(select(DiscoveryPick.as_of).where(
        DiscoveryPick.as_of <= as_of).distinct().order_by(
        DiscoveryPick.as_of.desc()).limit(consecutive)).all()
    if len(days) < consecutive:
        return []
    weak = []
    for code in held:
        is_weak = True
        for d in days:
            picks = session.scalars(select(DiscoveryPick).where(
                DiscoveryPick.as_of == d)).all()
            total = len(picks)
            row = next((p for p in picks if p.code == code), None)
            # 不在当日截面=视为弱;在截面则看百分位是否跌出前 pctl
            if row is not None and total and (row.rank / total) <= pctl:
                is_weak = False
                break
        if is_weak:
            weak.append(code)
    return sorted(weak)
