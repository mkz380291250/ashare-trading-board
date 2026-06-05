from datetime import date
from typing import Callable, Optional
from sqlalchemy import delete
from sqlalchemy.orm import Session
from app.db.models import Decision
from app.decision.graph import DecisionGraph
from app.decision.brief import StockBrief
from app.trading.broker import PaperBroker, InsufficientFunds, InsufficientShares


class DecisionRunner:
    def __init__(self, session: Session, graph: DecisionGraph,
                 broker: Optional[PaperBroker] = None, account_id: int = 1,
                 price_of: Optional[Callable[[str], Optional[float]]] = None):
        self.s = session
        self.graph = graph
        self.broker = broker
        self.account_id = account_id
        self.price_of = price_of

    def run(self, as_of: date, briefs: list[StockBrief]) -> list[Decision]:
        out = []
        for brief in briefs:
            d = self.graph.run(brief)
            self.s.execute(delete(Decision).where(
                Decision.as_of == as_of, Decision.code == brief.code))
            status = "PENDING"
            reasoning = d.reasoning
            if self.broker is not None:
                status = "APPROVED"
                if d.action in ("BUY", "SELL") and d.shares > 0:
                    price = self.price_of(brief.code) if self.price_of else None
                    if price:
                        try:
                            if d.action == "BUY":
                                self.broker.buy(self.account_id, brief.code, price, d.shares, as_of)
                            else:
                                self.broker.sell(self.account_id, brief.code, price, d.shares, as_of)
                        except (InsufficientFunds, InsufficientShares) as e:
                            reasoning += f"\n\n⚠️ 自动执行失败:{e}"
                    else:
                        reasoning += "\n\n⚠️ 自动执行跳过:无最新价"
            row = Decision(as_of=as_of, code=brief.code, action=d.action,
                           confidence=d.confidence, shares=d.shares,
                           reasoning=reasoning, status=status, created_at=as_of)
            self.s.add(row); out.append(row)
        self.s.commit()
        return out
