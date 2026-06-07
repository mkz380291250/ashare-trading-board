import pytest
from datetime import date
from app.quant.ml_pipeline import label_expr, make_segments


def test_label_expr_5day_horizon():
    exprs, names = label_expr(5)
    # T+1 买入,T+6 卖出 -> Ref(-6)/Ref(-1)-1
    assert exprs == ["Ref($close, -6)/Ref($close, -1) - 1"]
    assert names == ["LABEL0"]


def test_label_expr_1day_horizon():
    exprs, _ = label_expr(1)
    assert exprs == ["Ref($close, -2)/Ref($close, -1) - 1"]


def test_make_segments_ordered():
    segs = make_segments(
        train=(date(2021, 1, 1), date(2024, 6, 30)),
        valid=(date(2024, 7, 1), date(2025, 6, 30)),
        test=(date(2025, 7, 1), date(2026, 6, 5)))
    assert segs["train"] == [date(2021, 1, 1), date(2024, 6, 30)]
    assert segs["test"][1] == date(2026, 6, 5)


def test_make_segments_rejects_overlap():
    with pytest.raises(ValueError):
        make_segments(
            train=(date(2021, 1, 1), date(2024, 7, 15)),
            valid=(date(2024, 7, 1), date(2025, 6, 30)),
            test=(date(2025, 7, 1), date(2026, 6, 5)))
