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


def test_scorer_requires_full_coverage():
    factors = {"f1": {"a": 1.0, "b": 2.0}, "f2": {"a": 5.0}}  # b missing f2
    picks = DiscoveryScorer(top_n=8).score(factors)
    assert [p[0] for p in picks] == ["a"]  # only a has all factors


def test_scorer_weights():
    factors = {"f1": {"a": 1.0, "b": 2.0}, "f2": {"a": 2.0, "b": 1.0}}
    picks = DiscoveryScorer(top_n=2, weights={"f1": 1.0, "f2": 0.0}).score(factors)
    assert picks[0][0] == "b"  # f1 dominant, b higher on f1
