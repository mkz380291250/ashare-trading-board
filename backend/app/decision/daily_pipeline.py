# backend/app/decision/daily_pipeline.py
"""每日决策编排:有界迭代选候选 → 建 brief → 辩论 → 自动执行 → 返回摘要。
幂等:当日已决策的代码不重复辩论/下单。所有外部依赖(graph/brief_builder/broker)可注入。"""
from datetime import date
from typing import Callable, Optional
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.db.models import Decision
from app.decision.brief import StockBrief
from app.decision.graph import DecisionGraph
from app.decision.runner import DecisionRunner
from app.decision.selection import select_debate_candidates
from app.trading.broker import PaperBroker


def today_decided_codes(session: Session, as_of: date) -> set[str]:
    rows = session.scalars(select(Decision.code).where(Decision.as_of == as_of)).all()
    return set(rows)


def run_daily_decisions(session: Session, as_of: date,
                        ranking: list[tuple[str, float]], held_codes: set[str], *,
                        graph: DecisionGraph,
                        brief_builder: Callable[[list[str]], list[StockBrief]],
                        broker: Optional[PaperBroker], price_of: Callable[[str], float], target: int,
                        quality_pctl: float, min_confidence: float, max_debate: int,
                        account_id: int = 1,
                        buy_filter: Optional[Callable[[str], bool]] = None) -> dict:
    skip = today_decided_codes(session, as_of)
    # Pass held_codes | skip as effective held so already-decided codes count
    # against the target slot budget, preventing idempotency violations.
    effective_held = set(held_codes) | skip
    candidates = select_debate_candidates(
        ranking, effective_held, target=target, quality_pctl=quality_pctl,
        max_debate=max_debate, skip=skip, buy_filter=buy_filter)
    briefs = brief_builder(candidates)
    runner = DecisionRunner(session, graph, broker=broker, account_id=account_id,
                            price_of=price_of, min_confidence=min_confidence)
    decisions = runner.run(as_of, briefs)
    n_buy = sum(1 for d in decisions if d.action == "BUY" and d.status == "APPROVED")
    n_sell = sum(1 for d in decisions if d.action == "SELL" and d.status == "APPROVED")
    n_hold = sum(1 for d in decisions if d.action == "HOLD")
    n_lowconf = sum(1 for d in decisions if d.status == "LOW_CONF")
    return {"candidates": candidates, "n_debated": len(decisions),
            "n_buy": n_buy, "n_sell": n_sell, "n_hold": n_hold, "n_lowconf": n_lowconf}
