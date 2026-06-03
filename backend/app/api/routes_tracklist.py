from datetime import date
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select, desc
from sqlalchemy.orm import Session
from app.api.deps import get_session
from app.db.models import DailyQuote
from app.screener.tracklist import Tracker
from app.screener.tracklist_parser import parse_tracklist

router = APIRouter(prefix="/api/track", tags=["track"])


class AddReq(BaseModel):
    text: str


def _latest_trade_date(s: Session) -> date | None:
    return s.scalars(select(DailyQuote.trade_date)
                     .order_by(desc(DailyQuote.trade_date)).limit(1)).first()


def _row(e):
    return {"code": e.code, "name": e.name, "added_on": e.added_on.isoformat(),
            "entry_close": e.entry_close, "ret_t1": e.ret_t1, "ret_t3": e.ret_t3,
            "ret_t5": e.ret_t5, "ret_t10": e.ret_t10, "last_close": e.last_close,
            "ret_since": e.ret_since, "max_gain": e.max_gain,
            "max_drawdown": e.max_drawdown,
            "last_updated": e.last_updated.isoformat() if e.last_updated else None}


@router.post("")
def add(req: AddReq, s: Session = Depends(get_session)):
    on = _latest_trade_date(s)
    if on is None:
        return {"added": [], "error": "no market data"}
    pairs = parse_tracklist(req.text)
    codes = [c for c, _ in pairs]
    quotes = {q.code: q.close for q in s.scalars(
        select(DailyQuote).where(DailyQuote.code.in_(codes),
                                 DailyQuote.trade_date == on)).all()}
    added = Tracker(s).add(pairs, on=on, closes=quotes)
    return {"added": [_row(e) for e in added]}


@router.get("")
def list_all(s: Session = Depends(get_session)):
    return [_row(e) for e in Tracker(s).list()]


@router.delete("/{code}/{on}")
def remove(code: str, on: date, s: Session = Depends(get_session)):
    Tracker(s).remove(code, on)
    return {"ok": True}
