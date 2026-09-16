from datetime import date
from app.quant.universe import filter_investable, write_instruments


def test_filter_removes_st_and_star_st():
    rows = [
        ("600519.SH", "贵州茅台", date(2001, 8, 27)),
        ("000004.SZ", "*ST国华", date(1991, 1, 14)),
        ("000078.SZ", "ST海王", date(1998, 12, 18)),
    ]
    codes = filter_investable(rows, as_of=date(2026, 6, 5))
    assert codes == ["600519.SH"]


def test_filter_removes_recent_ipo_within_window():
    rows = [
        ("600519.SH", "贵州茅台", date(2001, 8, 27)),
        ("301999.SZ", "次新股", date(2026, 5, 1)),  # 上市仅 35 天
    ]
    codes = filter_investable(rows, as_of=date(2026, 6, 5), min_list_days=120)
    assert codes == ["600519.SH"]


def test_filter_keeps_exactly_at_window_boundary():
    rows = [("600000.SH", "浦发银行", date(2026, 2, 5))]  # 距 6-5 正好 120 天
    codes = filter_investable(rows, as_of=date(2026, 6, 5), min_list_days=120)
    assert codes == ["600000.SH"]


def test_filter_skips_rows_missing_list_date():
    rows = [("600000.SH", "浦发银行", None)]
    assert filter_investable(rows, as_of=date(2026, 6, 5)) == []


def test_write_instruments_qlib_format(tmp_path):
    path = tmp_path / "investable.txt"
    write_instruments(["600519.SH", "000001.SZ"], str(path),
                      start=date(2021, 1, 4), end=date(2026, 6, 5))
    lines = path.read_text().strip().splitlines()
    assert lines[0] == "SH600519\t2021-01-04\t2026-06-05"
    assert lines[1] == "SZ000001\t2021-01-04\t2026-06-05"


def test_dynamic_rows_start_end_and_filters():
    from datetime import date
    from app.quant.universe import dynamic_rows
    rows = [
        ("300001.SZ", "特锐德", date(2009, 10, 30), None),            # 老票:从 cal_start 起
        ("300999.SZ", "新票", date(2026, 6, 1), None),               # 次新:list+120 天 > cal_end → 剔除
        ("300500.SZ", "退市股", date(2015, 1, 1), date(2020, 6, 1)),  # 退市:end = delist−1
        ("300600.SZ", "*ST烂", date(2015, 1, 1), None),              # ST 剔除
        ("000001.SZ", "平安银行", date(1991, 4, 3), None),           # 非创业板
        ("300700.SZ", "刚满", date(2011, 1, 1), None),               # start = 2011-05-01
    ]
    out = dynamic_rows(rows, cal_start=date(2011, 1, 4), cal_end=date(2026, 9, 15))
    d = {c: (s, e) for c, s, e in out}
    assert d["300001.SZ"] == (date(2011, 1, 4), date(2026, 9, 15))
    assert "300999.SZ" not in d and "300600.SZ" not in d and "000001.SZ" not in d
    assert d["300500.SZ"] == (date(2015, 5, 1), date(2020, 5, 31))
    assert d["300700.SZ"] == (date(2011, 5, 1), date(2026, 9, 15))


def test_dynamic_rows_no_prefix_means_all():
    from datetime import date
    from app.quant.universe import dynamic_rows
    rows = [("000001.SZ", "平安银行", date(1991, 4, 3), None)]
    out = dynamic_rows(rows, cal_start=date(2011, 1, 4), cal_end=date(2026, 9, 15), prefixes=())
    assert [c for c, _, _ in out] == ["000001.SZ"]


def test_write_instrument_rows(tmp_path):
    from datetime import date
    from app.quant.universe import write_instrument_rows
    p = tmp_path / "cyb_dyn.txt"
    n = write_instrument_rows([("300001.SZ", date(2011, 1, 4), date(2026, 9, 15))], p)
    assert n == 1
    assert p.read_text() == "SZ300001\t2011-01-04\t2026-09-15\n"
