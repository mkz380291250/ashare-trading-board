import numpy as np
import pandas as pd
import pytest
from app.quant.pit_fields import (
    quarterly_derive, align_pit, dps_ttm, moneyflow_daily, PitFields, PIT_COLS)


def _inc(rows):
    return pd.DataFrame(rows, columns=["ann_date", "end_date", "revenue", "n_income_attr_p"])


def test_ttm_uses_single_quarter_diffs_across_year_boundary():
    # 2024Q1..2024Q4 的 ytd 净利:10,25,45,70 | 2025Q1=15
    inc = _inc([
        ("20240425", "20240331", 100.0, 10.0),
        ("20240820", "20240630", 220.0, 25.0),
        ("20241028", "20240930", 350.0, 45.0),
        ("20250328", "20241231", 500.0, 70.0),
        ("20250426", "20250331", 130.0, 15.0),
    ])
    empty = pd.DataFrame()
    q = quarterly_derive(inc, empty, empty, empty)
    # 单季:10,15,20,25,15 → 2025Q1 TTM = 15+20+25+15 = 75
    last = q.iloc[-1]
    assert last["end_date"] == "20250331"
    assert last["np_ttm"] == pytest.approx(75.0)
    assert last["rev_ttm"] == pytest.approx(130 + 120 + 130 + 150)
    # 前三季不足 4 个单季 → TTM NaN
    assert np.isnan(q.iloc[0]["np_ttm"]) and np.isnan(q.iloc[2]["np_ttm"])
    assert q.iloc[3]["np_ttm"] == pytest.approx(70.0)
    # 2025Q1 单季 15 vs 2024Q1 单季 10 → +50%
    assert last["q_profit_yoy"] == pytest.approx(50.0)


def test_sue_is_yoy_diff_over_std_of_diffs():
    # 单季净利:前 12 季每季比去年同季 +2(差恒为 2,含微小噪声),最后一季差=6
    rows, ytd = [], 0.0
    vals = [1, 2, 3, 4, 3, 4.01, 5, 6, 5, 6, 7.02, 8, 7, 8, 9, 14]  # 单季
    for i, v in enumerate(vals):
        yr = 2021 + i // 4
        qn = i % 4
        ytd = v if qn == 0 else ytd + v
        end = f"{yr}{['0331', '0630', '0930', '1231'][qn]}"
        rows.append((end, end, 0.0, ytd))
    q = quarterly_derive(_inc(rows), pd.DataFrame(), pd.DataFrame(), pd.DataFrame())
    assert q.iloc[-1]["sue"] > 3.0          # 最后一季 yoy 差=6,历史差≈2,std 极小 → 大 SUE
    assert np.isnan(q.iloc[4]["sue"])       # 不足 8 季历史


def test_align_pit_no_lookahead_and_restatement_wins_by_ann_date():
    q = pd.DataFrame({
        "ann_date": ["20250428", "20250428", "20250830"],
        "end_date": ["20250331", "20241231", "20250630"],   # 同 ann_date 两份:取 end_date 最新
        "q_roe": [5.0, 99.0, 7.0], "gm": [30.0, 31.0, 32.0],
    })
    dates = pd.to_datetime(["2025-04-25", "2025-04-28", "2025-04-29", "2025-08-29", "2025-09-01"])
    out = align_pit(q, dates)
    assert np.isnan(out.loc["2025-04-25", "q_roe"])         # 公告前 NaN
    assert out.loc["2025-04-28", "q_roe"] == 5.0             # 同 ann_date 取 end_date 最新
    assert out.loc["2025-08-29", "q_roe"] == 5.0
    assert out.loc["2025-09-01", "q_roe"] == 7.0
    assert out.loc["2025-04-28", "ann_age"] == 0
    assert out.loc["2025-04-29", "ann_age"] == 1
    assert out.loc["2025-08-29", "ann_age"] == 2             # 4/28=0, 4/29=1, 8/29=2
    assert out.loc["2025-09-01", "ann_age"] == 0             # 8/30(周六)公告 → 9/1 为 0
    assert np.isnan(out.loc["2025-04-25", "ann_age"])


def test_dps_ttm_window_by_ex_date():
    div = pd.DataFrame({
        "div_proc": ["实施", "实施", "预案"],
        "ex_date": ["20240610", "20250605", "20250701"],
        "cash_div_tax": [1.0, 2.0, 9.0],
    })
    dates = pd.to_datetime(["2024-06-09", "2024-06-10", "2025-06-04", "2025-06-05",
                            "2025-06-11", "2025-07-02"])
    s = dps_ttm(div, dates)
    assert s.loc["2024-06-09"] == 0.0
    assert s.loc["2024-06-10"] == 1.0
    assert s.loc["2025-06-04"] == 1.0                        # 365 天内仍算
    assert s.loc["2025-06-05"] == 3.0
    assert s.loc["2025-06-11"] == 2.0                        # 2024-06-10 已出窗
    assert s.loc["2025-07-02"] == 2.0                        # 预案不算


def test_moneyflow_daily_units():
    mf = pd.DataFrame({
        "trade_date": ["20250102"], "buy_sm_amount": [10.0], "sell_sm_amount": [4.0],
        "buy_lg_amount": [100.0], "sell_lg_amount": [30.0],
        "buy_elg_amount": [50.0], "sell_elg_amount": [20.0], "net_mf_amount": [7.0],
    })
    dates = pd.to_datetime(["2025-01-02", "2025-01-03"])
    out = moneyflow_daily(mf, dates)
    assert out.loc["2025-01-02", "mf_lg_net"] == 100.0       # (100+50)-(30+20)
    assert out.loc["2025-01-02", "mf_sm_net"] == 6.0
    assert out.loc["2025-01-02", "mf_net"] == 7.0
    assert np.isnan(out.loc["2025-01-03", "mf_lg_net"])      # 无数据日不 ffill


def test_pitfields_missing_code_gives_nan_columns(tmp_path):
    import sqlite3
    db = tmp_path / "x.db"
    con = sqlite3.connect(db)
    for t, cols in [
        ("ts_income", "ts_code,ann_date,end_date,revenue,n_income_attr_p"),
        ("ts_cashflow", "ts_code,ann_date,end_date,n_cashflow_act"),
        ("ts_balancesheet", "ts_code,ann_date,end_date,total_assets"),
        ("ts_fina_indicator",
         "ts_code,ann_date,end_date,q_roe,grossprofit_margin,q_sales_yoy,debt_to_assets"),
        ("ts_dividend", "ts_code,div_proc,ex_date,cash_div_tax"),
        ("ts_moneyflow", "ts_code,trade_date,buy_sm_amount,sell_sm_amount,buy_lg_amount,"
                         "sell_lg_amount,buy_elg_amount,sell_elg_amount,net_mf_amount"),
    ]:
        con.execute(f"create table {t} ({cols})")
    con.commit()
    con.close()
    pit = PitFields(str(db))
    dates = pd.to_datetime(["2025-01-02", "2025-01-03"])
    out = pit.for_code("000001.SZ", dates)
    assert list(out.columns) == PIT_COLS
    assert len(out) == 2
    # dps_ttm 无分红 → 0;其余全 NaN
    assert (out["dps_ttm"] == 0.0).all()
    assert out.drop(columns=["dps_ttm"]).isna().all().all()


def test_pitfields_moneyflow_off_skips_table(tmp_path):
    import sqlite3
    db = tmp_path / "y.db"
    con = sqlite3.connect(db)
    con.execute("create table ts_income (ts_code,ann_date,end_date,revenue,n_income_attr_p)")
    con.execute("insert into ts_income values ('300750.SZ','20250315','20241231',100.0,10.0)")
    # 故意不建 ts_moneyflow 之外的表:moneyflow=False 时不应触碰资金流表;其余缺表 → NaN
    con.commit()
    con.close()
    pit = PitFields(str(db), moneyflow=False)
    dates = pd.to_datetime(["2025-03-17", "2025-03-18"])
    out = pit.for_code("300750.SZ", dates)
    assert out["mf_lg_net"].isna().all()
    assert out.loc["2025-03-17", "ann_age"] == 0


def test_pitfields_preload_matches_per_code_queries(tmp_path):
    import sqlite3
    db = tmp_path / "z.db"
    con = sqlite3.connect(db)
    con.execute("create table ts_income (ts_code,ann_date,end_date,revenue,n_income_attr_p)")
    con.execute("create table ts_dividend (ts_code,div_proc,ex_date,cash_div_tax)")
    for y in range(2021, 2026):
        for q, (md, ytd) in enumerate([("0331", 10), ("0630", 25), ("0930", 45), ("1231", 70)]):
            ann = f"{y}{md}" if md != "1231" else f"{y + 1}0328"
            con.execute("insert into ts_income values (?,?,?,?,?)",
                        ("300750.SZ", ann, f"{y}{md}", 100.0 * (q + 1), float(ytd + y - 2021)))
    con.execute("insert into ts_dividend values ('300750.SZ','实施','20250605',2.0)")
    con.commit()
    con.close()
    dates = pd.bdate_range("2025-01-01", "2025-12-31")
    a = PitFields(str(db), moneyflow=False, preload=True).for_code("300750.SZ", dates)
    b = PitFields(str(db), moneyflow=False, preload=False).for_code("300750.SZ", dates)
    pd.testing.assert_frame_equal(a, b)
    assert a["np_ttm"].notna().any() and (a["dps_ttm"].max() == 2.0)
    # 内存里没有的票 → 全 NaN(分红 0)
    c = PitFields(str(db), moneyflow=False, preload=True).for_code("000001.SZ", dates)
    assert c.drop(columns=["dps_ttm"]).isna().all().all()
