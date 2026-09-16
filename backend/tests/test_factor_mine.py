from app.quant.factor_mine import (
    FACTOR_LIBRARY, STYLE_FACTORS, FUNDAMENTAL_FACTORS, FLOW_FACTORS,
    RESEARCH_ONLY, FACTOR_FAMILY, required_fields)

_BASE_FIELDS = {"open", "high", "low", "close", "volume",
                "turnover_rate", "volume_ratio", "circ_mv", "total_mv",
                "pe", "pb", "amount"}
_PIT_FIELDS = {"np_ttm", "rev_ttm", "ocf_ttm", "sue", "q_roe", "gm", "q_sales_yoy",
               "q_profit_yoy", "profit_acc", "accrual", "debt_to_assets", "total_assets",
               "ann_age", "dps_ttm", "mf_lg_net", "mf_sm_net", "mf_net"}


def test_style_factors_present_and_fields_valid():
    expected = {"ln_mv", "mv_chg20", "ep", "bp", "turn5", "turn20",
                "turn_chg5_20", "turn_std20", "amihud_amt20", "amt5_20",
                "vr5", "vr_chg"}
    assert expected == set(STYLE_FACTORS)
    assert expected <= set(FACTOR_LIBRARY)
    for name in expected:
        assert required_fields(name) <= _BASE_FIELDS, name


def test_fundamental_and_flow_factors_reference_pit_fields():
    assert len(FUNDAMENTAL_FACTORS) == 16
    assert len(FLOW_FACTORS) == 5
    for name in list(FUNDAMENTAL_FACTORS) + list(FLOW_FACTORS):
        assert name in FACTOR_LIBRARY
        assert required_fields(name) <= _BASE_FIELDS | _PIT_FIELDS, name
        assert required_fields(name) & _PIT_FIELDS, f"{name} 应至少用一个 PIT 字段"
    assert RESEARCH_ONLY == frozenset(FLOW_FACTORS)


def test_pit_fields_match_pit_module():
    from app.quant.pit_fields import PIT_COLS
    assert set(PIT_COLS) == _PIT_FIELDS


def test_every_factor_has_family():
    assert set(FACTOR_LIBRARY) == set(FACTOR_FAMILY)
    assert FACTOR_FAMILY["vol20"] == "波动" and FACTOR_FAMILY["ep_ttm"] == "估值"
    assert FACTOR_FAMILY["lg_net5"] == "资金流"


def test_library_total_count():
    assert len(FACTOR_LIBRARY) == 36 + 12 + 16 + 5
