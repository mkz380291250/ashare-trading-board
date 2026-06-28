from datetime import date as date_t
from fastapi import APIRouter, Depends
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from app.api.deps import get_session
from app.db.models import FactorICDaily, DecisionOutcome
from app.attribution.outcomes import hit_rate

router = APIRouter(prefix="/api", tags=["attribution"])


@router.get("/attribution/hit-rate")
def get_hit_rate(window: int = 30, s: Session = Depends(get_session)):
    as_of = s.scalar(select(func.max(DecisionOutcome.decided_on))) or date_t.today()
    start = date_t.fromordinal(as_of.toordinal() - window)
    n = s.scalar(select(func.count()).select_from(DecisionOutcome).where(
        DecisionOutcome.decided_on >= start, DecisionOutcome.decided_on <= as_of,
        DecisionOutcome.hit.is_not(None))) or 0
    return {"window": window, "hit_rate": hit_rate(s, window=window, as_of=as_of), "n": int(n)}


@router.get("/attribution/forward-ic")
def get_forward_ic(days: int = 60, s: Session = Depends(get_session)):
    rows = s.scalars(select(FactorICDaily).order_by(
        FactorICDaily.as_of.desc()).limit(days)).all()
    rows = sorted(rows, key=lambda r: r.as_of)
    return [{"as_of": r.as_of.isoformat(), "ic": r.ic, "rank_ic": r.rank_ic, "n": r.n}
            for r in rows]
