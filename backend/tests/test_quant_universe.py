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
