from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.api.deps import get_session
from app.db.models import PolicyAction

router = APIRouter(prefix="/api", tags=["policy"])


@router.get("/policy/actions")
def policy_actions(limit: int = 50, s: Session = Depends(get_session)):
    rows = s.scalars(select(PolicyAction).order_by(
        PolicyAction.as_of.desc(), PolicyAction.id.desc()).limit(limit)).all()
    return [{"id": r.id, "kind": r.kind, "as_of": r.as_of.isoformat(),
             "trigger": r.trigger, "detail": r.detail, "status": r.status} for r in rows]
