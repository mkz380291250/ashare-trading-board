"""组合再平衡纯函数:再平衡日判定、TopkDropout 买卖清单、等权定股数。不触 DB/qlib。"""
from datetime import date
from math import floor


def is_rebalance_day(as_of: date, weekday: int) -> bool:
    return as_of.weekday() == weekday


def plan_rebalance(ranked, held, *, topk: int, buffer: int):
    """ranked: list[(code, rank)](rank 从 1);held: 持仓 code 集合。
    返回 (sells, buy_candidates):
      sells = 持仓中 rank>topk+buffer 或已不在 ranked 的(排序);
      buy_candidates = 未持仓、rank 最靠前的 slots+buffer 个(slots=补满 topk 的空位)。"""
    held = set(held)
    rank_of = {c: r for c, r in ranked}
    ranked_codes = [c for c, _ in sorted(ranked, key=lambda x: x[1])]
    sells = sorted(c for c in held
                   if c not in rank_of or rank_of[c] > topk + buffer)
    remaining = len(held) - len(sells)
    slots = max(0, topk - remaining)
    if slots <= 0:
        return sells, []
    buy_candidates = [c for c in ranked_codes if c not in held][: slots + buffer]
    return sells, buy_candidates


def equal_weight_shares(equity: float, topk: int, price: float, lot: int = 100) -> int:
    if equity <= 0 or topk <= 0 or price <= 0:
        return 0
    budget = equity / topk
    return int(floor(budget / price / lot)) * lot
