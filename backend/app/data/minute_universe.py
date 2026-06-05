from sqlalchemy import select
from sqlalchemy.orm import Session
from app.db.models import Position, TrackEntry, Decision, DecisionJob


def minute_universe(session: Session) -> list[str]:
    """需要落库并盘中实时更新的关注股集合:
    输入辩论(decision_jobs)∪ 跟踪(tracklist)∪ 已辩论决策(decisions)∪ 持仓(positions)。
    去重,返回排序后的 code 列表。"""
    codes: set[str] = set()
    for model in (DecisionJob, TrackEntry, Decision, Position):
        codes.update(session.scalars(select(model.code)).all())
    codes.discard(None)
    codes.discard("")
    return sorted(codes)
