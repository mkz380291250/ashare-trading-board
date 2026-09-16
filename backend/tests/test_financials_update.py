import sqlite3
import pandas as pd
from datetime import date
from app.data.financials_update import (
    profit_rows, upsert_income, pending_quarters, update_financials)


def _db(tmp_path):
    db = tmp_path / "x.db"
    con = sqlite3.connect(db)
    con.execute("create table ts_income (ts_code TEXT, ann_date TEXT, f_ann_date TEXT, end_date TEXT, "
                "report_type TEXT, revenue REAL, n_income_attr_p REAL)")
    con.execute("insert into ts_income values ('300750.SZ','20260725','20260725','20260630','1',2.7e11,4.3e10)")
    con.commit()
    con.close()
    return str(db)


def test_profit_rows_maps_baostock_columns():
    df = pd.DataFrame([{"code": "sz.300750", "pubDate": "2026-10-25", "statDate": "2026-09-30",
                        "MBRevenue": "4.1e11", "netProfit": "6.5e10", "roeAvg": "0.1"}])
    rows = profit_rows(df, "300750.SZ")
    assert rows == [{"ts_code": "300750.SZ", "ann_date": "20261025", "end_date": "20260930",
                     "revenue": 4.1e11, "n_income_attr_p": 6.5e10}]
    assert profit_rows(pd.DataFrame(), "300750.SZ") == []
    # 缺 pubDate 或空营收 → 跳过
    df2 = pd.DataFrame([{"code": "sz.300750", "pubDate": "", "statDate": "2026-09-30",
                         "MBRevenue": "", "netProfit": "1"}])
    assert profit_rows(df2, "300750.SZ") == []


def test_upsert_income_only_new_periods(tmp_path):
    db = _db(tmp_path)
    con = sqlite3.connect(db)
    rows = [{"ts_code": "300750.SZ", "ann_date": "20260725", "end_date": "20260630",
             "revenue": 9.9, "n_income_attr_p": 9.9},                          # 已有 → 跳过
            {"ts_code": "300750.SZ", "ann_date": "20261025", "end_date": "20260930",
             "revenue": 4.1e11, "n_income_attr_p": 6.5e10}]                     # 新 → 插入
    n = upsert_income(con, rows)
    assert n == 1
    got = con.execute("select ann_date,end_date,revenue,report_type from ts_income "
                      "where ts_code='300750.SZ' order by end_date").fetchall()
    assert got == [("20260725", "20260630", 2.7e11, "1"), ("20261025", "20260930", 4.1e11, "1")]
    assert upsert_income(con, rows) == 0                                        # 幂等


def test_pending_quarters_skips_periods_already_in_db(tmp_path):
    db = _db(tmp_path)
    con = sqlite3.connect(db)
    # 2026-11-01:可能已披露 2026Q3、2026Q2;Q2 已在库 → 只查 Q3
    assert pending_quarters(con, "300750.SZ", date(2026, 11, 1), n=2) == [(2026, 3)]
    # 新票一条都没有 → 两个季度都查
    assert pending_quarters(con, "301999.SZ", date(2026, 11, 1), n=2) == [(2026, 3), (2026, 2)]


def test_update_financials_uses_fetch_fn_and_counts(tmp_path):
    db = _db(tmp_path)
    calls = []

    def fetch(code, year, quarter):
        calls.append((code, year, quarter))
        if (code, year, quarter) == ("300750.SZ", 2026, 3):
            return pd.DataFrame([{"pubDate": "2026-10-25", "statDate": "2026-09-30",
                                  "MBRevenue": "4.1e11", "netProfit": "6.5e10"}])
        return pd.DataFrame()

    stats = update_financials(db, ["300750.SZ", "301999.SZ"], fetch_fn=fetch,
                              today=date(2026, 11, 1), n=2)
    assert stats == {"codes": 2, "queries": 3, "inserted": 1, "errors": 0}
    assert ("300750.SZ", 2026, 2) not in calls                                  # 已有的不查
    con = sqlite3.connect(db)
    assert con.execute("select count(*) from ts_income where end_date='20260930'").fetchone()[0] == 1
