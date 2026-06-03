from app.screener.tracklist_parser import parse_tracklist, normalize_code


def test_normalize_code_exchange_suffix():
    assert normalize_code("300975") == "300975.SZ"   # 创业板
    assert normalize_code("301099") == "301099.SZ"
    assert normalize_code("603045") == "603045.SH"   # 沪市主板
    assert normalize_code("601991") == "601991.SH"
    assert normalize_code("688519") == "688519.SH"   # 科创板
    assert normalize_code("830799") == "830799.BJ"   # 北交所
    assert normalize_code("300975.SZ") == "300975.SZ"  # 已带后缀原样返回


SAMPLE = """
19:51    同花顺App
同花顺自选
4075.10+17.36
上证指数+0.43%
最新    涨幅    现手
商络电子    43.41    +12.72%    4
融    300975
福达合金    75.26    +10.00%    86
融    603045
大唐发电    601991    9.18    +9.68%    16.6万
江丰电子    209.22    +11.25%
300666
力源信息    18.26    +15.13%
融    300184
南亚新材    238.92    +10.33%    5
融    688519
新锐股份    98.21    +8.20%
融    688257
雅创电子    71.47    +10.40%    1533
融    301099
凯格精机    258.44    +10.21%
融    301338
东杰智能    29.98    +20.02%    12
创    300486
"""


def test_parse_extracts_ten_codes():
    out = parse_tracklist(SAMPLE)
    codes = [c for c, _ in out]
    assert codes == ["300975", "603045", "601991", "300666", "300184",
                     "688519", "688257", "301099", "301338", "300486"]


def test_parse_pairs_names():
    out = dict(parse_tracklist(SAMPLE))
    assert out["300975"] == "商络电子"
    assert out["601991"] == "大唐发电"   # name on same line as code
    assert out["300666"] == "江丰电子"   # name on previous line


def test_parse_dedups_and_ignores_index_numbers():
    out = parse_tracklist(SAMPLE)
    assert len(out) == 10
    assert all(c.isdigit() and len(c) == 6 for c, _ in out)


def test_parse_empty():
    assert parse_tracklist("没有任何代码") == []
