import re
from app.quant.factor_mine import FACTOR_LIBRARY, STYLE_FACTORS

_KNOWN_FIELDS = {"open", "high", "low", "close", "volume",
                 "turnover_rate", "volume_ratio", "circ_mv", "total_mv",
                 "pe", "pb", "amount"}


def test_style_factors_present_and_fields_valid():
    expected = {"ln_mv", "mv_chg20", "ep", "bp", "turn5", "turn20",
                "turn_chg5_20", "turn_std20", "amihud_amt20", "amt5_20",
                "vr5", "vr_chg"}
    assert expected == set(STYLE_FACTORS)
    assert expected <= set(FACTOR_LIBRARY)
    for name in expected:
        fields = set(re.findall(r"\$([a-z_]+)", FACTOR_LIBRARY[name]))
        assert fields <= _KNOWN_FIELDS, f"{name} 引用未知字段 {fields}"


def test_library_total_count():
    assert len(FACTOR_LIBRARY) == 36 + 12
