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

    def score(self, factors: dict[str, dict[str, float]]):
        """factors: {factor_name: {code: raw}}. Returns sorted list of
        (code, total_score, {factor: raw}) truncated to top_n."""
        if not factors:
            return []
        names = list(factors.keys())
        weights = self.weights or {n: 1.0 / len(names) for n in names}
        pct = {n: percentile_rank(factors[n]) for n in names}
        common = set(factors[names[0]])
        for n in names[1:]:
            common &= set(factors[n])
        scored = []
        for code in common:
            total = sum(weights.get(n, 0.0) * pct[n][code] for n in names)
            raw = {n: factors[n][code] for n in names}
            scored.append((code, total, raw))
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[: self.top_n]
