from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.api.deps import get_session
from app.trading.broker import PaperBroker, InsufficientFunds, InsufficientShares
from app.trading.schemas import TradeRequest

router = APIRouter(prefix="/api", tags=["trade"])


@router.post("/trade")
def trade(req: TradeRequest, s: Session = Depends(get_session)):
    broker = PaperBroker(s)
    try:
        if req.side == "BUY":
            broker.buy(req.account_id, req.code, req.price, req.shares, req.on)
        elif req.side == "SELL":
            broker.sell(req.account_id, req.code, req.price, req.shares, req.on)
        else:
            raise HTTPException(400, "side must be BUY or SELL")
    except (InsufficientFunds, InsufficientShares) as e:
        raise HTTPException(400, str(e))
    return {"status": "ok"}
