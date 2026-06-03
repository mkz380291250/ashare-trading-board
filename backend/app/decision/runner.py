from datetime import date
from sqlalchemy import delete
from sqlalchemy.orm import Session
from app.db.models import Decision
from app.decision.graph import DecisionGraph
from app.decision.brief import StockBrief


class DecisionRunner:
    def __init__(self, session: Session, graph: DecisionGraph):
        self.s = session
        self.graph = graph

    def run(self, as_of: date, briefs: list[StockBrief]) -> list[Decision]:
        out = []
        for brief in briefs:
            d = self.graph.run(brief)
            self.s.execute(delete(Decision).where(
                Decision.as_of == as_of, Decision.code == brief.code))
            row = Decision(as_of=as_of, code=brief.code, action=d.action,
                           confidence=d.confidence, shares=d.shares,
                           reasoning=d.reasoning, status="PENDING", created_at=as_of)
            self.s.add(row); out.append(row)
        self.s.commit()
        return out
