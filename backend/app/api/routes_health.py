import json
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.api.deps import get_session
from app.db.models import SchedulerRun

router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health/last-run")
def last_run(s: Session = Depends(get_session)):
    """最近一次每日自动运行的状态(无则返回 null)。"""
    r = s.scalars(select(SchedulerRun).order_by(SchedulerRun.id.desc()).limit(1)).first()
    if r is None:
        return None
    steps = json.loads(r.detail or "[]")
    return {
        "as_of": r.as_of.isoformat(),
        "started_at": r.started_at.isoformat() if r.started_at else None,
        "finished_at": r.finished_at.isoformat() if r.finished_at else None,
        "ok": r.ok,
        "failed_steps": [x["step"] for x in steps if not x.get("ok")],
        "steps": steps,
    }
