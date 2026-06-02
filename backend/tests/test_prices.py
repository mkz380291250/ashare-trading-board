from app.data.prices import DictPriceProvider


def test_dict_price_provider():
    p = DictPriceProvider({"600519.SH": 1500.0, "000001.SZ": 12.3})
    assert p.latest_close("600519.SH") == 1500.0
    assert p.latest_close("000001.SZ") == 12.3


def test_missing_code_raises():
    p = DictPriceProvider({})
    try:
        p.latest_close("X")
        assert False, "expected KeyError"
    except KeyError:
        pass
