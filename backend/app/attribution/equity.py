"""权益回撤与滚动胜率(纯计算,无 DB)。供日报与 Phase 3b 策略闸读取。"""


def current_drawdown(totals: list[float]) -> float | None:
    if not totals:
        return None
    peak = max(totals)
    return (totals[-1] / peak - 1.0) if peak else 0.0


def rolling_hit_rate(hits: list[bool | None]) -> float | None:
    valid = [h for h in hits if h is not None]
    return (sum(1 for h in valid if h) / len(valid)) if valid else None
