from app.quant.factor_select import rank_importance, candidate_subsets, pick_best


def test_rank_importance_descending():
    imp = {"MA5": 10.0, "ROC5": 50.0, "STD20": 30.0}
    assert rank_importance(imp) == ["ROC5", "STD20", "MA5"]


def test_candidate_subsets_includes_topn_and_all():
    ranked = ["a", "b", "c", "d", "e"]
    subs = candidate_subsets(ranked, sizes=[2, 3])
    assert subs["top2"] == ["a", "b"]
    assert subs["top3"] == ["a", "b", "c"]
    assert subs["all"] == ranked


def test_candidate_subsets_caps_size_at_available():
    subs = candidate_subsets(["a", "b"], sizes=[5])
    assert subs["top5"] == ["a", "b"]


def test_pick_best_by_information_ratio():
    results = {
        "top10": {"information_ratio": 0.5, "annualized_return": 0.1},
        "top50": {"information_ratio": 1.2, "annualized_return": 0.2},
        "all": {"information_ratio": 0.9, "annualized_return": 0.3},
    }
    name, metrics = pick_best(results, metric="information_ratio")
    assert name == "top50"
    assert metrics["information_ratio"] == 1.2


def test_pick_best_ignores_none_metric():
    results = {
        "a": {"information_ratio": None},
        "b": {"information_ratio": 0.3},
    }
    name, _ = pick_best(results, metric="information_ratio")
    assert name == "b"
