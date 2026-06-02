import json
from datetime import date as date_t
from fastapi import APIRouter, Depends
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from app.api.deps import get_session
from app.db.models import DiscoveryPick

router = APIRouter(prefix="/api", tags=["discovery"])


@router.get("/discovery")
def discovery(date: date_t | None = None, s: Session = Depends(get_session)):
    target = date
    if target is None:
        target = s.scalar(select(func.max(DiscoveryPick.as_of)))
    if target is None:
        return []
    rows = s.scalars(
        select(DiscoveryPick).where(DiscoveryPick.as_of == target)
        .order_by(DiscoveryPick.rank)
    ).all()
    return [{"as_of": r.as_of.isoformat(), "code": r.code, "rank": r.rank,
             "score": r.score, "factors": json.loads(r.factors or "{}")} for r in rows]
