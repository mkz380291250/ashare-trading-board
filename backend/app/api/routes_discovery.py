import json
from datetime import date as date_t
from fastapi import APIRouter, Depends
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from app.api.deps import get_session
from app.data.names import NameLookup
from app.db.models import DiscoveryPick

router = APIRouter(prefix="/api", tags=["discovery"])


@router.get("/discovery")
def discovery(date: date_t | None = None, limit: int = 50,
              s: Session = Depends(get_session)):
    """选股榜。limit 默认 50(全量1338行曾卡死手机端渲染);limit=0 返回全量。"""
    target = date
    if target is None:
        target = s.scalar(select(func.max(DiscoveryPick.as_of)))
    if target is None:
        return []
    q = (select(DiscoveryPick).where(DiscoveryPick.as_of == target)
         .order_by(DiscoveryPick.rank))
    if limit > 0:
        q = q.limit(limit)
    rows = s.scalars(q).all()
    names = NameLookup(s).map([r.code for r in rows])
    return [{"as_of": r.as_of.isoformat(), "code": r.code, "name": names.get(r.code, ""),
             "rank": r.rank, "score": r.score, "factors": json.loads(r.factors or "{}")} for r in rows]
