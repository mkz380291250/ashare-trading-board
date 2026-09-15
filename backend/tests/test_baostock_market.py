from datetime import date
import pandas as pd
from app.data.baostock_market import (RefRow, rows_from_baostock, rows_from_tencent,
                                      needs_adj_query, is_bj, BaostockMarketFetcher)


def _k(rows):
    cols = ["date", "code", "open", "high", "low", "close", "preclose", "volume",
            "amount", "turn", "tradestatus", "peTTM", "pbMRQ"]
    return pd.DataFrame([dict(zip(cols, r)) for r in rows]).astype(str)


REF = RefRow(trade_date=date(2026, 9, 10), close=10.0, adj_factor=5.0,
             circ_mv=100000.0, total_mv=200000.0)      # 万元;流通股本 1e8 股


def test_no_exdiv_carries_db_factor_and_only_emits_new_days():
    k = _k([
        ["2026-09-09", "sz.000001", 9.9, 10.1, 9.8, 9.9, 9.8, 1_000_000, 9.9e6, 1.0, 1, 5.5, 0.9],
        ["2026-09-10", "sz.000001", 10, 10.2, 9.9, 10.0, 9.9, 1_000_000, 1.0e7, 1.0, 1, 5.5, 0.9],
        ["2026-09-11", "sz.000001", 10, 10.5, 9.9, 10.5, 10.0, 2_000_000, 2.1e7, 2.0, 1, 5.7, 0.95],
    ])
    assert needs_adj_query(k, REF) is False
    rows = rows_from_baostock("000001.SZ", k, None, REF)
    assert [r["trade_date"] for r in rows] == [date(2026, 9, 11)]
    r = rows[0]
    assert r["adj_factor"] == 5.0                     # 沿用库内因子
    assert r["vol"] == 20000.0                        # 股 → 手
    assert r["amount"] == 21000.0                     # 元 → 千元
    assert abs(r["circ_mv"] - 105000.0) < 1e-6        # 10.5 × 1e8 股 / 1e4
    assert abs(r["total_mv"] - 210000.0) < 1e-6       # 总/流通比 2 外推
    assert r["pe"] == 5.7 and r["pb"] == 0.95 and r["pre_close"] == 10.0
    assert r["turnover_rate"] == 2.0


def test_exdiv_queries_factor_and_rescales_to_db_scale():
    k = _k([
        ["2026-09-10", "sh.600519", 10, 10, 10, 10.0, 9.9, 1_000_000, 1e7, 1.0, 1, "", ""],
        ["2026-09-11", "sh.600519", 9, 9, 9, 9.0, 9.0, 1_000_000, 9e6, 1.0, 1, "", ""],  # 除权:preclose≠10
    ])
    assert needs_adj_query(k, REF) is True
    adj = pd.DataFrame({"dividOperateDate": ["2020-01-01", "2026-09-11"],
                        "backAdjustFactor": ["1.0", "1.1"]}).astype(str)
    rows = rows_from_baostock("600519.SH", k, adj, REF)
    assert len(rows) == 1
    # 源因子 09-10=1.0 ↔ 库因子 5.0 → scale 5;09-11 源 1.1 → 5.5
    assert abs(rows[0]["adj_factor"] - 5.5) < 1e-9
    assert rows[0]["pe"] is None


def test_new_stock_without_ref_uses_source_scale_and_emits_all():
    k = _k([
        ["2026-09-10", "sz.301999", 10, 10, 10, 10.0, "", 1_000_000, 1e7, 1.0, 1, "", ""],
        ["2026-09-11", "sz.301999", 11, 11, 11, 11.0, 10.0, 1_000_000, 1.1e7, 1.0, 1, "", ""],
    ])
    assert needs_adj_query(k, None) is True
    adj = pd.DataFrame({"dividOperateDate": ["2026-09-10"], "backAdjustFactor": ["1.0"]})
    rows = rows_from_baostock("301999.SZ", k, adj, None)
    assert len(rows) == 2 and rows[0]["adj_factor"] == 1.0
    assert rows[0]["total_mv"] is None and rows[0]["pre_close"] is None


def test_suspended_rows_dropped_and_volume_ratio():
    rows = [["2026-09-0%d" % i, "sz.000001", 10, 10, 10, 10.0, 10.0, 1_000_000, 1e7, 1.0, 1, "", ""]
            for i in range(1, 8)]
    rows.append(["2026-09-08", "sz.000001", "", "", "", "", "", "", "", "", 0, "", ""])
    rows.append(["2026-09-11", "sz.000001", 10, 10, 10, 10.0, 10.0, 3_000_000, 3e7, 3.0, 1, "", ""])
    ref = RefRow(date(2026, 9, 7), 10.0, 1.0, None, None)
    out = rows_from_baostock("000001.SZ", _k(rows), None, ref)
    assert [r["trade_date"] for r in out] == [date(2026, 9, 11)]
    assert out[0]["volume_ratio"] == 3.0


def test_ref_missing_from_window_forces_adj_query():
    k = _k([["2026-09-11", "sz.000001", 10, 10, 10, 10.0, 10.0, 1, 1, 1.0, 1, "", ""]])
    assert needs_adj_query(k, REF) is True


def test_rows_from_tencent_bj_with_quote_and_exdiv():
    ref = RefRow(date(2026, 9, 10), 22.4, 1.0151, 54432.0, 181865.6)
    raw = [["2026-09-10", "19.90", "22.40", "23.72", "19.62", "75693.000"],
           ["2026-09-11", "21.50", "22.10", "22.66", "20.73", "58586.000"],
           ["2026-09-14", "21.23", "20.48", "21.75", "20.06", "42221.000"]]
    hfq = [["2026-09-10", "20.40", "22.90", "24.22", "20.12", "75693.000"],
           ["2026-09-11", "22.00", "22.60", "23.16", "21.23", "58586.000"],
           ["2026-09-14", "21.73", "20.98", "22.25", "20.56", "42221.000"]]
    quote = {"date": date(2026, 9, 11), "close": 22.1, "amount": 125995.1, "turnover_rate": 24.11,
             "pe": 96.4, "pb": 3.53, "circ_mv": 53703.0, "total_mv": 179429.9}
    out = rows_from_tencent("920128.BJ", raw, hfq, ref, quote, max_date=date(2026, 9, 11))
    assert [r["trade_date"] for r in out] == [date(2026, 9, 11)]   # 09-14 盘中被截掉
    r = out[0]
    assert r["vol"] == 58586.0 and r["amount"] == 125995.1
    # 换手/流通市值按库内流通股本(54432万/22.4)算,比腾讯 2 位小数精确:tushare 原值 24.1095
    assert r["turnover_rate"] == 24.1095
    assert abs(r["circ_mv"] - 54432.0 * 22.1 / 22.4) < 1e-6
    assert r["pre_close"] == 22.4 and r["pb"] == 3.53
    assert abs(r["adj_factor"] - 1.0151) < 1e-12        # 无除权:沿用库内因子
    assert is_bj("920128.BJ") and not is_bj("600519.SH")


def test_rows_from_tencent_exdiv_updates_factor_and_extrapolates_without_quote():
    # 10派1(除权日 09-11):raw 收盘 9.9,hfq 收盘不变 → 比值跳变 10/9.9... 用整数好算:
    ref = RefRow(date(2026, 9, 10), 10.0, 2.0, 100000.0, 200000.0, pe=20.0, pb=2.0)
    raw = [["2026-09-10", "10", "10", "10", "10", "1000"],
           ["2026-09-11", "9", "9", "9", "9", "1000"]]
    hfq = [["2026-09-10", "20", "20", "20", "20", "1000"],
           ["2026-09-11", "19.8", "19.8", "19.8", "19.8", "1000"]]   # hfq/raw: 2.0 → 2.2
    out = rows_from_tencent("000001.SZ", raw, hfq, ref, None)
    r = out[0]
    assert abs(r["adj_factor"] - 2.2) < 1e-9      # 库因子 2.0 × (2.2/2.0)
    assert abs(r["pre_close"] - 9.09) < 1e-9      # 10 × 2.0/2.2
    assert r["amount"] is None
    assert r["turnover_rate"] == 0.1        # 1000手=1e5股 / 流通股本 1e8 股
    assert abs(r["circ_mv"] - 90000.0) < 1e-6 and abs(r["total_mv"] - 180000.0) < 1e-6
    assert r["pe"] == 18.0 and r["pb"] == 1.8   # 按价格比例外推


def test_rows_from_tencent_share_change_switches_to_quote_shares():
    ref = RefRow(date(2026, 9, 10), 10.0, 1.0, 100000.0, 200000.0)
    raw = [["2026-09-10", "10", "10", "10", "10", "1000"], ["2026-09-11", "10", "10", "10", "10", "1000"]]
    quote = {"date": date(2026, 9, 11), "close": 10.0, "amount": 1.0, "turnover_rate": 0.05,
             "pe": 1.0, "pb": 1.0, "circ_mv": 200000.0, "total_mv": 200000.0}   # 流通股本翻倍(解禁)
    r = rows_from_tencent("000001.SZ", raw, raw, ref, quote)[0]
    assert r["circ_mv"] == 200000.0 and r["total_mv"] == 200000.0
    assert r["turnover_rate"] == 0.05


class _BSFail:
    """login 成功、查询永远失败的假 baostock,验证熔断切腾讯。"""
    def login(self):
        class R: error_code = "0"; error_msg = ""
        return R()

    def logout(self):
        pass

    def query_history_k_data_plus(self, *a, **k):
        raise TimeoutError("timed out")


def test_fetcher_breaker_falls_back_to_tencent():
    from app.data.baostock_source import BaostockSource
    ref = RefRow(date(2026, 9, 10), 10.0, 1.0, 100000.0, 100000.0)
    codes = [f"60000{i}.SH" for i in range(8)] + ["920128.BJ"]
    refs = {c: ref for c in codes}

    def kl(code, start, end, fq):
        return [["2026-09-10", "10", "10", "10", "10", "1000"],
                ["2026-09-11", "11", "11", "11", "11", "2000"]]
    logs = []
    f = BaostockMarketFetcher(log=lambda *a, **k: logs.append(a[0]),
                              bs_src=BaostockSource(bs=_BSFail()),
                              tx_klines=kl, tx_quotes=lambda codes: {})
    out = f.fetch(codes, refs, date(2026, 9, 1), date(2026, 9, 11))
    assert set(out) == {date(2026, 9, 11)}
    assert sorted(r["code"] for r in out[date(2026, 9, 11)]) == sorted(codes)
    assert any("熔断" in m for m in logs)


def _q(day, close, pre_close, vol, circ_mv=None, total_mv=None, **kw):
    d = {"date": day, "open": close, "high": close, "low": close, "close": close,
         "pre_close": pre_close, "vol": vol, "amount": 1000.0, "turnover_rate": 0.5,
         "pe": 10.0, "pb": 1.5, "circ_mv": circ_mv, "total_mv": total_mv}
    d.update(kw)
    return d


def test_rows_from_quotes_carry_factor_and_ref_shares():
    from app.data.baostock_market import rows_from_quotes
    day = date(2026, 9, 14)
    ref = RefRow(date(2026, 9, 11), 10.0, 5.0, 100000.0, 200000.0, vols5=(100, 100, 100, 100, 100))
    quotes = {"000001.SZ": _q(day, 11.0, 10.0, 200.0, circ_mv=110000.0, total_mv=220000.0),
              "000002.SZ": _q(date(2026, 9, 10), 11.0, 10.0, 200.0),      # 停牌:快照停在旧日期
              "000003.SZ": _q(day, 9.0, 9.0, 100.0, circ_mv=90000.0)}      # 除权:昨收 9 ≠ 前收 10
    refs = {"000001.SZ": ref, "000002.SZ": ref, "000003.SZ": ref}
    rows = {r["code"]: r for r in rows_from_quotes(day, quotes, refs, sorted(quotes))}
    assert set(rows) == {"000001.SZ", "000003.SZ"}
    r = rows["000001.SZ"]
    assert r["adj_factor"] == 5.0 and r["volume_ratio"] == 2.0
    assert abs(r["turnover_rate"] - 0.02) < 1e-9          # 200手=2e4股 / 1e8股
    assert abs(r["circ_mv"] - 110000.0) < 1e-6 and abs(r["total_mv"] - 220000.0) < 1e-6
    assert r["pe"] == 10.0 and r["amount"] == 1000.0 and r["pre_close"] == 10.0
    assert abs(rows["000003.SZ"]["adj_factor"] - 5.0 * 10.0 / 9.0) < 1e-9


def test_fetch_uses_quote_path_when_no_gap_and_kline_for_gaps():
    day, prev = date(2026, 9, 14), date(2026, 9, 11)
    ref_ok = RefRow(prev, 10.0, 1.0, 100000.0, 100000.0)
    ref_gap = RefRow(date(2026, 9, 10), 10.0, 1.0, 100000.0, 100000.0)
    refs = {"000001.SZ": ref_ok, "000002.SZ": ref_gap}
    quotes = {c: _q(day, 11.0, 10.0, 100.0, circ_mv=110000.0) for c in refs}
    kl_calls = []

    def kl(code, start, end, fq):
        kl_calls.append((code, fq))
        return [["2026-09-10", "10", "10", "10", "10", "1000"], ["2026-09-11", "10", "10.5", "10", "10", "1000"],
                ["2026-09-14", "10", "11", "10", "10", "1000"]]
    f = BaostockMarketFetcher(log=lambda *a, **k: None, use_baostock=False,
                              tx_klines=kl, tx_quotes=lambda codes: quotes)
    out = f.fetch(sorted(refs), refs, date(2026, 9, 8), day,
                  trading_days=[date(2026, 9, 8), date(2026, 9, 9), date(2026, 9, 10), prev, day])
    assert [r["code"] for r in out[prev]] == ["000002.SZ"]            # 缺的 09-11 由 K 线补
    assert sorted(r["code"] for r in out[day]) == ["000001.SZ", "000002.SZ"]
    assert {c for c, _ in kl_calls} == {"000002.SZ"}                    # 没缺天的不拉 K 线
