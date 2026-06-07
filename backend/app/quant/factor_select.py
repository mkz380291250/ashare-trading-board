"""因子评估与最优组合选择。"""

_NEG_INF = float("-inf")


def rank_importance(importance: dict[str, float]) -> list[str]:
    """按重要性降序返回因子名列表。"""
    return [k for k, _ in sorted(importance.items(), key=lambda kv: -kv[1])]


def candidate_subsets(ranked: list[str], sizes: list[int]) -> dict[str, list[str]]:
    """构造候选因子子集:每个 size 取排名前 N(超出则取全部),外加 'all' 全集。"""
    out = {f"top{n}": ranked[:n] for n in sizes}
    out["all"] = list(ranked)
    return out


def pick_best(results: dict[str, dict], metric: str = "information_ratio"):
    """从 {子集名: 指标dict} 中按 metric 取最高(None 视为最差)。返回 (名, 指标dict)。"""
    def key(kv):
        v = kv[1].get(metric)
        return v if v is not None else _NEG_INF
    return max(results.items(), key=key)
