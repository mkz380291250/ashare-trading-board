import pytest
from app.backtest.symbols import to_qlib_symbol, from_qlib_symbol


def test_to_qlib_symbol_sh_sz_bj():
    assert to_qlib_symbol("600519.SH") == "SH600519"
    assert to_qlib_symbol("000001.SZ") == "SZ000001"
    assert to_qlib_symbol("920128.BJ") == "BJ920128"


def test_from_qlib_symbol_roundtrip():
    for code in ["600519.SH", "000001.SZ", "920128.BJ"]:
        assert from_qlib_symbol(to_qlib_symbol(code)) == code


def test_invalid_raises():
    with pytest.raises(ValueError):
        to_qlib_symbol("600519")        # 无交易所后缀
    with pytest.raises(ValueError):
        from_qlib_symbol("600519.SH")   # 不是 qlib 符号
