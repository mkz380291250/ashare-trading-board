from app.discovery.scorer import percentile_rank, DiscoveryScorer


def test_percentile_rank_handles_ties():
    pr = percentile_rank({"a": 10.0, "b": 20.0, "c": 20.0, "d": 30.0})
    assert pr["a"] == 0.25
    assert abs(pr["b"] - 0.625) < 1e-9 and abs(pr["c"] - 0.625) < 1e-9
    assert pr["d"] == 1.0


def test_scorer_ranks_and_truncates():
    # both factors agree: c > b > a, so order is unambiguous
    factors = {
        "f1": {"a": 1.0, "b": 2.0, "c": 3.0},
        "f2": {"a": 1.0, "b": 2.0, "c": 3.0},
    }
    picks = DiscoveryScorer(top_n=2).score(factors)
    assert len(picks) == 2
    assert picks[0][0] == "c" and picks[1][0] == "b"
    assert "a" not in [p[0] for p in picks]
    assert picks[0][2] == {"f1": 3.0, "f2": 3.0}   # raw factor values of the winner


def test_scorer_uses_union_with_neutral_fill():
    # b 缺 f2 → f2 按中性 0.5 计;a 两因子齐全
    factors = {"f1": {"a": 1.0, "b": 2.0}, "f2": {"a": 5.0}}
    picks = DiscoveryScorer(top_n=8).score(factors)
    codes = [p[0] for p in picks]
    assert set(codes) == {"a", "b"}  # 并集,两只都进


def test_scorer_weights():
    factors = {"f1": {"a": 1.0, "b": 2.0}, "f2": {"a": 2.0, "b": 1.0}}
    picks = DiscoveryScorer(top_n=2, weights={"f1": 1.0, "f2": 0.0}).score(factors)
    assert picks[0][0] == "b"  # f1 dominant, b higher on f1


def test_scorer_momentum_only_matches_intersection_regression():
    # 所有因子覆盖全部 code 时,并集==交集,排名与旧行为一致
    factors = {
        "f1": {"a": 1.0, "b": 2.0, "c": 3.0},
        "f2": {"a": 1.0, "b": 2.0, "c": 3.0},
    }
    picks = DiscoveryScorer(top_n=3).score(factors)
    assert [p[0] for p in picks] == ["c", "b", "a"]


def test_scorer_sparse_factor_neutral_does_not_penalize():
    # 稀疏研报因子:只有 c 有正情绪,a/b 缺该因子按 0.5
    factors = {
        "mom": {"a": 0.5, "b": 0.5, "c": 0.5},     # 动量持平
        "research_sent": {"c": 1.0},                # 只有 c 有研报
    }
    picks = DiscoveryScorer(top_n=3).score(factors)
    assert picks[0][0] == "c"  # 有正研报的 c 排第一
