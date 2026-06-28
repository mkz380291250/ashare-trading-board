"""策略动作统一审计入口:落 policy_actions 表。关键动作的 weixin 推送由 step_policy
打印交运维层投递(初始 weixin_sent=False)。"""
import json
from datetime import date
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.db.models import PolicyAction


def already_recorded(session: Session, kind: str, as_of: date) -> bool:
    return session.scalar(select(PolicyAction).where(
        PolicyAction.kind == kind, PolicyAction.as_of == as_of)) is not None


def record_action(session: Session, kind: str, as_of: date, trigger: dict,
                  detail: str, *, status: str = "AUTO") -> PolicyAction:
    pa = PolicyAction(kind=kind, as_of=as_of, trigger=json.dumps(trigger, ensure_ascii=False),
                      detail=detail, status=status, weixin_sent=False, created_at=as_of)
    session.add(pa)
    session.commit()
    return pa
