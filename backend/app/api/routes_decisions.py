from datetime import date as date_t
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from app.api.deps import get_session
from app.db.models import Decision
from app.trading.broker import PaperBroker, InsufficientFunds, InsufficientShares

router = APIRouter(prefix="/api", tags=["decisions"])


class ApproveBody(BaseModel):
    price: float = 0.0
    account_id: int = 1


@router.get("/decisions")
def list_decisions(date: date_t | None = None, s: Session = Depends(get_session)):
    target = date or s.scalar(select(func.max(Decision.as_of)))
    if target is None:
        return []
    rows = s.scalars(select(Decision).where(Decision.as_of == target)
                     .order_by(Decision.code)).all()
    return [{"id": r.id, "as_of": r.as_of.isoformat(), "code": r.code,
             "action": r.action, "confidence": r.confidence, "shares": r.shares,
             "status": r.status, "reasoning": r.reasoning} for r in rows]


@router.post("/decisions/{decision_id}/approve")
def approve(decision_id: int, body: ApproveBody, s: Session = Depends(get_session)):
    d = s.get(Decision, decision_id)
    if d is None:
        raise HTTPException(404, "decision not found")
    if d.status != "PENDING":
        return {"status": d.status}
    if d.action in ("BUY", "SELL") and d.shares > 0:
        broker = PaperBroker(s)
        try:
            if d.action == "BUY":
                broker.buy(body.account_id, d.code, body.price, d.shares, d.as_of)
            else:
                broker.sell(body.account_id, d.code, body.price, d.shares, d.as_of)
        except (InsufficientFunds, InsufficientShares) as e:
            raise HTTPException(400, str(e))
    d.status = "APPROVED"
    s.commit()
    return {"status": "APPROVED"}


@router.post("/decisions/{decision_id}/reject")
def reject(decision_id: int, s: Session = Depends(get_session)):
    d = s.get(Decision, decision_id)
    if d is None:
        raise HTTPException(404, "decision not found")
    d.status = "REJECTED"; s.commit()
    return {"status": "REJECTED"}
