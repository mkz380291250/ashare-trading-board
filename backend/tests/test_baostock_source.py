from datetime import date
import pandas as pd
from app.data.baostock_source import BaostockSource, to_bs_code, to_ts_code


class FakeRS:
    """Row-iterating result set like baostock's (next/get_row_data/fields)."""
    def __init__(self, df):
        self._rows = df.astype(str).values.tolist()
        self.fields = list(df.columns)
        self._i = -1
        self.error_code = "0"
        self.error_msg = "success"

    def next(self):
        self._i += 1
        return self._i < len(self._rows)

    def get_row_data(self):
        return self._rows[self._i]


class FakeBS:
    """Mimics the baostock module surface we use. Strings everywhere, like the
    real thing; suspended day (tradestatus=0) included to check it is dropped."""
    def __init__(self):
        self.logged_in = 0

    def login(self):
        self.logged_in += 1
        return FakeRS(pd.DataFrame())

    def logout(self):
        self.logged_in -= 1

    def query_history_k_data_plus(self, code, fields, start_date, end_date,
                                  frequency, adjustflag):
        assert code == "sh.600519" and adjustflag == "3"
        return FakeRS(pd.DataFrame({
            "date": ["2026-01-02", "2026-01-05", "2026-01-06"],
            "code": [code] * 3,
            "open": ["10.0", "", "11.0"], "high": ["10.5", "", "11.5"],
            "low": ["9.8", "", "10.8"], "close": ["10.0", "", "11.0"],
            "volume": ["100000", "", "200000"],   # 股 (tushare vol is 手)
            "tradestatus": ["1", "0", "1"],
        }))

    def query_adjust_factor(self, code, start_date, end_date):
        # step function: factor 1.0 until the 2026-01-06 dividend, 2.0 after
        return FakeRS(pd.DataFrame({
            "code": [code, code],
            "dividOperateDate": ["2020-06-30", "2026-01-06"],
            "backAdjustFactor": ["1.0", "2.0"],
        }))


def test_code_conversion():
    assert to_bs_code("600519.SH") == "sh.600519"
    assert to_bs_code("300750.SZ") == "sz.300750"
    assert to_ts_code("sz.300750") == "300750.SZ"


def test_returns_sorted_bars_with_factor_and_drops_suspended():
    src = BaostockSource(bs=FakeBS())
    bars = src.get_daily_bars("600519.SH", date(2026, 1, 1), date(2026, 1, 10))
    assert [b.trade_date for b in bars] == [date(2026, 1, 2), date(2026, 1, 6)]
    assert bars[0].code == "600519.SH"
    assert bars[0].close == 10.0 and bars[0].adj_factor == 1.0
    assert bars[1].close == 11.0 and bars[1].adj_factor == 2.0
    assert bars[1].volume == 2000.0   # 200000 股 → 2000 手


def test_factor_before_first_dividend_defaults_to_earliest():
    bs = FakeBS()
    src = BaostockSource(bs=bs)
    bars = src.get_daily_bars("600519.SH", date(2026, 1, 1), date(2026, 1, 3))
    assert bars[0].adj_factor == 1.0
