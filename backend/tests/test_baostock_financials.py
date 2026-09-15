from datetime import date
import pandas as pd
from app.data.baostock_financials import BaostockFinancials, _quarters
from app.data.baostock_source import BaostockSource


class FakeRS:
    def __init__(self, rows, fields):
        self._rows, self.fields, self._i = rows, fields, -1
        self.error_code, self.error_msg = "0", "ok"

    def next(self):
        self._i += 1
        return self._i < len(self._rows)

    def get_row_data(self):
        return self._rows[self._i]


class FakeBS:
    """只有 2026Q2 与 2025Q2 有数据;其余季度空(模拟 Q3 未披露)。"""
    calls = []

    def login(self):
        return FakeRS([], [])

    def logout(self):
        pass

    def query_profit_data(self, code, year, quarter):
        self.calls.append(("profit", year, quarter))
        f = ["code", "pubDate", "statDate", "roeAvg", "npMargin", "gpMargin", "netProfit",
             "epsTTM", "MBRevenue", "totalShare", "liqaShare"]
        if (year, quarter) == (2026, 2):
            return FakeRS([[code, "2026-08-15", "2026-06-30", "0.18", "0.5", "0.8956",
                            "46033330566.78", "65.1", "92278072083.21", "1", "1"]], f)
        if (year, quarter) == (2025, 2):
            return FakeRS([[code, "2025-08-15", "2025-06-30", "0.19", "0.5", "0.9",
                            "47000000000", "66", "83889156439.28", "1", "1"]], f)
        return FakeRS([], f)

    def query_growth_data(self, code, year, quarter):
        f = ["code", "pubDate", "statDate", "YOYEquity", "YOYAsset", "YOYNI", "YOYEPSBasic", "YOYPNI"]
        return FakeRS([[code, "", "2026-06-30", "0.05", "0.05", "-0.02", "-0.016", "-0.019516"]], f)

    def query_balance_data(self, code, year, quarter):
        f = ["code", "pubDate", "statDate", "currentRatio", "quickRatio", "cashRatio",
             "YOYLiability", "liabilityToAsset", "assetToEquity"]
        return FakeRS([[code, "", "2026-06-30", "5.5", "4.2", "1.1", "0.08", "0.151931", "1.18"]], f)

    def query_cash_flow_data(self, code, year, quarter):
        f = ["code", "pubDate", "statDate", "CAToAsset", "NCAToAsset", "tangibleAssetToAsset",
             "ebitToInterest", "CFOToOR", "CFOToNP", "CFOToGr"]
        return FakeRS([[code, "", "2026-06-30", "0.84", "0.15", "0.76", "", "0.78", "1.535643", "0.77"]], f)


def test_quarters_walk_backwards():
    assert _quarters(date(2026, 9, 14), 4) == [(2026, 2), (2026, 1), (2025, 4), (2025, 3)]
    assert _quarters(date(2026, 1, 10), 2) == [(2025, 4), (2025, 3)]


def test_latest_and_summary():
    fb = FakeBS()
    fin = BaostockFinancials(BaostockSource(bs=fb), today=date(2026, 9, 14))
    e = fin.latest("600519.SH")
    assert abs(e.np_yoy - (-1.9516)) < 1e-6
    assert abs(e.rev_yoy - 10.0) < 1e-6           # 922.78 / 838.89 - 1
    s = fin.summary("600519.SH")
    assert s["报告期"] == "20260630"
    assert s["营收_亿"] == 922.78 and s["归母净利_亿"] == 460.33
    assert s["毛利率"] == 89.56 and s["ROE"] == 18.0 and s["资产负债率"] == 15.19
    assert s["现金流净利比"] == 1.54 and s["经营现金流_亿"] == 706.91
    assert s["净利同比"] == -1.95 and s["营收同比"] == 10.0
    # 每只股票四张表只拉一次(缓存),Q3 空后回退到 Q2
    assert fb.calls.count(("profit", 2026, 2)) == 1


def test_no_data_returns_none():
    class Empty(FakeBS):
        def query_profit_data(self, code, year, quarter):
            return FakeRS([], ["code"])
    fin = BaostockFinancials(BaostockSource(bs=Empty()), today=date(2026, 9, 14))
    assert fin.latest("000001.SZ") is None and fin.summary("000001.SZ") is None
