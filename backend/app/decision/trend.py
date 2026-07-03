"""买入趋势闸(pure):把"因子高分但正单边下跌/破位"的飞刀票挡在辩论之外。
判据:最近 window 根收盘的最后一根 >= 均线 *(1-tol)。数据不足则保守拒绝。"""


def is_uptrend(closes: list[float], *, window: int = 20, tol: float = 0.0) -> bool:
    seg = list(closes)[-window:]
    if len(seg) < window:
        return False                          # 数据不足,无法确认非下跌 → 不买
    ma = sum(seg) / len(seg)
    if ma <= 0:
        return False
    return seg[-1] >= ma * (1.0 - tol)
