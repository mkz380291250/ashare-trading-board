from app.screener.themes import StaticThemeSource, TushareThemeSource


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
