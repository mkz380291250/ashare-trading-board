"""再平衡编排:plan → 辩论 SELL 否决 → 先卖后买(等权)→ 落 Decision。依赖全注入,可测。"""
import traceback
from sqlalchemy import delete
from app.db.models import Decision
from app.decision.llm import UsageLimitError
from app.portfolio.rebalance import plan_rebalance, equal_weight_shares


def rebalance_portfolio(session, as_of, ranking, holdings, *, graph, broker,
                        brief_builder, price_of, equity_of, topk, buffer,
                        risk_off=False, account_id=1) -> dict:
    holdings = set(holdings)
    sells, buy_pool = plan_rebalance(ranking, holdings, topk=topk, buffer=buffer)
    if risk_off:
        buy_pool = []
    sell_set = set(sells)

    # 辩论:持仓 ∪ 买候选;取 verdict
    debate_codes = sorted(holdings | set(buy_pool))
    briefs = brief_builder(debate_codes)
    verdicts = {}
    for b in briefs:
        try:
            verdicts[b.code] = graph.run(b)
        except UsageLimitError:
            raise                                   # 全局限额:整场中止(上层重试)
        except Exception as exc:                    # noqa: BLE001
            print(f"DEBATE_SKIP {b.code}: {exc!r}", flush=True)
            traceback.print_exc()

    # 持仓 SELL 否决 → 并入卖
    for c in holdings:
        v = verdicts.get(c)
        if v is not None and v.action == "SELL":
            sell_set.add(c)

    # 补满空位:买候选按 rank 顺序取,SELL 者跳过
    remaining = len(holdings) - len(sell_set & holdings)
    slots = max(0, topk - remaining)
    buys, vetoed = [], []
    for c in buy_pool:
        v = verdicts.get(c)
        if v is not None and v.action == "SELL":
            vetoed.append(c)
            continue
        if len(buys) < slots:
            buys.append(c)

    # 执行:先卖后买
    sold = []
    for c in sorted(sell_set):
        pos = broker.get_position(account_id, c)
        if pos is None or pos.shares <= 0:
            continue
        p = price_of(c)
        if not p or p <= 0:
            continue
        try:
            broker.sell(account_id, c, p, pos.shares, as_of)
            sold.append(c)
        except Exception as exc:                    # noqa: BLE001
            print(f"SELL_SKIP {c}: {exc!r}", flush=True)

    equity = equity_of()                            # 卖后再算权益,供等权定股
    bought = []
    for c in buys:
        p = price_of(c)
        shares = equal_weight_shares(equity, topk, p or 0.0)
        if shares <= 0:
            continue
        try:
            broker.buy(account_id, c, p, shares, as_of)
            bought.append(c)
        except Exception as exc:                    # noqa: BLE001
            print(f"BUY_SKIP {c}: {exc!r}", flush=True)

    # 落 Decision 行(供 UI):先删同日同 code 再插
    held_final = sorted(holdings - set(sold))
    status_of = {}
    for c in bought:   status_of[c] = "EXECUTED"
    for c in sold:     status_of[c] = "SOLD"
    for c in held_final: status_of[c] = "HELD"
    for c in vetoed:   status_of.setdefault(c, "VETOED")
    for c in buy_pool:                              # 未用到的后备
        status_of.setdefault(c, "CANDIDATE")
    for c, st in status_of.items():
        v = verdicts.get(c)
        session.execute(delete(Decision).where(
            Decision.as_of == as_of, Decision.code == c))
        session.add(Decision(
            as_of=as_of, code=c,
            action=(v.action if v is not None else "HOLD"),
            confidence=(v.confidence if v is not None else 0.0),
            shares=0, reasoning=(v.reasoning if v is not None else ""),
            status=st, created_at=as_of))
    session.commit()

    return {"sold": sold, "bought": bought, "vetoed": vetoed,
            "held": held_final, "n_debated": len(verdicts)}
