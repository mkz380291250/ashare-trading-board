import json
import pytest
from app.factors.frozen import FrozenFactors, load_frozen, save_frozen


def _sample() -> FrozenFactors:
    return FrozenFactors(
        as_of="2026-06-25",
        factors=["vstd20", "rev3"],
        signs={"vstd20": -1.0, "rev3": 1.0},
        weights={"vstd20": 0.5, "rev3": 0.5},
        universe="investable",
        horizon=5,
        source_report="factor_mining_2026-06-25",
        metrics_at_freeze={"rank_ic_mean": 0.0695, "rank_ic_ir": 0.58},
    )


def test_save_load_roundtrip(tmp_path):
    p = tmp_path / "frozen_composite.json"
    save_frozen(_sample(), p)
    ff = load_frozen(p)
    assert ff.factors == ["vstd20", "rev3"]
    assert ff.signs["vstd20"] == -1.0
    assert ff.horizon == 5
    assert ff.metrics_at_freeze["rank_ic_ir"] == 0.58


def test_load_missing_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_frozen(tmp_path / "nope.json")


def test_save_archives_previous(tmp_path):
    p = tmp_path / "frozen_composite.json"
    save_frozen(_sample(), p)
    newer = _sample()
    newer.as_of = "2026-07-01"
    save_frozen(newer, p)
    archived = tmp_path / "archive" / "frozen_composite_2026-06-25.json"
    assert archived.exists()
    assert json.loads(archived.read_text())["as_of"] == "2026-06-25"
    assert load_frozen(p).as_of == "2026-07-01"
