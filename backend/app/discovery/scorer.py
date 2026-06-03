import pandas as pd


def percentile_rank(values: dict[str, float]) -> dict[str, float]:
    if not values:
        return {}
    s = pd.Series(values)
    ranked = s.rank(pct=True, method="average")
    return {k: float(v) for k, v in ranked.items()}


class DiscoveryScorer:
    def __init__(self, top_n: int = 8, weights: dict[str, float] | None = None):
        self.top_n = top_n
        self.weights = weights

    def score_all(self, factors: dict[str, dict[str, float]]):
        """同 score() 但不按 top_n 截断,返回全市场 (code, total, raw) 降序。"""
        if not factors:
            return []
        names = list(factors.keys())
        weights = self.weights or {n: 1.0 / len(names) for n in names}
        pct = {n: percentile_rank(factors[n]) for n in names}
        universe: set[str] = set()
        for n in names:
            universe |= set(factors[n])
        scored = []
        for code in universe:
            total = sum(weights.get(n, 0.0) * pct[n].get(code, 0.5) for n in names)
            raw = {n: factors[n][code] for n in names if code in factors[n]}
            scored.append((code, total, raw))
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored

    def score(self, factors: dict[str, dict[str, float]]):
        """全市场打分后截断到 top_n。"""
        return self.score_all(factors)[: self.top_n]
