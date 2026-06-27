"""有界迭代选候选:持仓必辩,买入候选按复合分排名填空位,卡质量门与单日上限。
不强迫交易——空仓合法,候选不够好就少辩甚至不买。"""


def select_debate_candidates(ranking: list[tuple[str, float]], held: set[str], *,
                             target: int, quality_pctl: float, max_debate: int,
                             skip: set[str] = frozenset()) -> list[str]:
    held = set(held)
    skip = set(skip)
    in_ranking = {c for c, _ in ranking}
    debate: list[str] = []
    # ① 持仓必辩(减去 skip);先排名内的,再排名外的(可能已退市但仍持有)
    for code, _ in ranking:
        if code in held and code not in skip:
            debate.append(code)
    for code in sorted(held - in_ranking - skip):
        debate.append(code)
    # ② 买入候选填空位,卡质量门
    slots = max(0, target - len(held))
    floor_idx = int(quality_pctl * len(ranking))
    for i, (code, _) in enumerate(ranking):
        if slots <= 0 or i >= floor_idx:
            break
        if code in held or code in skip:
            continue
        debate.append(code)
        slots -= 1
    # ③ 整体截断
    return debate[:max_debate]
