"""决策后向收益与命中:对 BUY/SELL 决策(已执行 APPROVED + 被置信度门拦下的
LOW_CONF,后者用于验证门槛是否错杀)从决策日收盘起算 ret_t1/t3/t5/t10,
命中以 t5 定(BUY 涨=命中,SELL 跌=命中)。回填幂等(按 decision_id upsert)。
hit_rate(喂风控停买闸)只统计 APPROVED,LOW_CONF 不影响停买判断。"""
from datetime import date, timedelta
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.screener.filters import forward_return
from app.db.models import Decision, DecisionOutcome

_OFFSETS = {"ret_t1": 1, "ret_t3": 3, "ret_t5": 5, "ret_t10": 10}


def compute_outcome(action: str, closes: list[float]) -> dict:
    entry = closes[0]
    rets = {}
    for field, n in _OFFSETS.items():
        fut = closes[n] if len(closes) > n else None
        rets[field] = forward_return(entry, fut)
    r5 = rets["ret_t5"]
    hit = None
    if r5 is not None:
        hit = (r5 > 0) if action == "BUY" else (r5 < 0)
    return {"entry_close": entry, **rets, "hit": hit}


def backfill_outcomes(session: Session, store, as_of: date, *,
                      lookback_days: int = 15) -> int:
    start = as_of - timedelta(days=lookback_days)
    decisions = session.scalars(select(Decision).where(
        Decision.as_of >= start, Decision.as_of <= as_of,
        Decision.status.in_(("APPROVED", "LOW_CONF")),
        Decision.action.in_(("BUY", "SELL")))).all()
    count = 0
    for d in decisions:
        bars = store.get_bars(d.code, d.as_of, as_of)
        closes = [b.close for b in bars if b.trade_date >= d.as_of]
        if not closes:
            continue
        oc = compute_outcome(d.action, closes)
        row = session.scalar(select(DecisionOutcome).where(
            DecisionOutcome.decision_id == d.id))
        if row is None:
            row = DecisionOutcome(decision_id=d.id, code=d.code, decided_on=d.as_of,
                                  action=d.action, entry_close=oc["entry_close"],
                                  last_updated=as_of)
            session.add(row)
        row.entry_close = oc["entry_close"]
        row.ret_t1, row.ret_t3 = oc["ret_t1"], oc["ret_t3"]
        row.ret_t5, row.ret_t10 = oc["ret_t5"], oc["ret_t10"]
        row.hit = oc["hit"]
        row.last_updated = as_of
        count += 1
    session.commit()
    return count


def hit_rate(session: Session, *, window: int = 30, as_of: date) -> float | None:
    start = as_of - timedelta(days=window)
    rows = session.scalars(select(DecisionOutcome).join(
        Decision, Decision.id == DecisionOutcome.decision_id).where(
        DecisionOutcome.decided_on >= start,
        DecisionOutcome.decided_on <= as_of,
        DecisionOutcome.hit.is_not(None),
        Decision.status == "APPROVED")).all()
    hits = [r.hit for r in rows]
    return (sum(1 for h in hits if h) / len(hits)) if hits else None
