from app.screener.themes import (
    EastMoneyThemeSource,
    StaticThemeSource,
    TushareThemeSource,
)


def test_static_theme_source():
    src = StaticThemeSource({"算力": ["A.SH", "B.SZ"], "电力": ["C.SH"]})
    assert src.themes() == ["算力", "电力"]
    assert src.members("算力") == ["A.SH", "B.SZ"]
    assert src.members("missing") == []


class FakePro:
    def ths_member(self, ts_code):
        import pandas as pd
        return pd.DataFrame({"con_code": ["A.SH", "B.SZ"]})


def test_tushare_theme_source_maps_index_to_members():
    src = TushareThemeSource(pro=FakePro(), index_by_theme={"算力": "885001.TI"})
    assert src.themes() == ["算力"]
    assert src.members("算力") == ["A.SH", "B.SZ"]


def test_eastmoney_theme_source_unions_boards_and_intersects_valid():
    by_board = {
        "英伟达概念": ["000034.SZ", "000818.SZ"],
        "CPO概念": ["000818.SZ", "300308.SZ", "999999.SZ"],
    }
    src = EastMoneyThemeSource(
        {"英伟达链": ["英伟达概念", "CPO概念"]},
        fetch_board=lambda b: by_board.get(b, []),
        valid={"000034.SZ", "000818.SZ", "300308.SZ"},  # 999999 not in DB -> dropped
    )
    assert src.themes() == ["英伟达链"]
    # union of both boards, deduped, filtered to valid, sorted
    assert src.members("英伟达链") == ["000034.SZ", "000818.SZ", "300308.SZ"]
    assert src.members("missing") == []


def test_eastmoney_theme_source_without_valid_keeps_all_codes():
    src = EastMoneyThemeSource(
        {"芯片": ["存储芯片"]},
        fetch_board=lambda b: ["688981.SH", "002049.SZ"],
    )
    assert src.members("芯片") == ["002049.SZ", "688981.SH"]
