"""深度财报数据:从 tushare 三大报表 + 财务指标提炼一份给「财报分析师」用的摘要。
每张表单独容错(限频/缺失不影响其余),全空则返回 None。金额统一换算成「亿元」。"""
import pandas as pd

_YI = 1e8


def _latest(df):
    if df is None or len(df) == 0:
        return None
    return df.sort_values("end_date").iloc[-1]


def _num(row, key):
    if row is None:
        return None
    v = row.get(key)
    return float(v) if v is not None and pd.notna(v) else None


class FinancialsSource:
    """pro = tushare pro_api;limiter 可选(每张表 acquire 一次)。"""

    def __init__(self, pro, limiter=None, lookback="20230101", asof="20991231"):
        self.pro = pro
        self.limiter = limiter
        self.lookback = lookback
        self.asof = asof

    def _fetch(self, fn, code):
        if self.limiter is not None:
            self.limiter.acquire()
        try:
            return _latest(fn(ts_code=code, start_date=self.lookback, end_date=self.asof))
        except Exception:
            return None

    def summary(self, code: str) -> dict | None:
        inc = self._fetch(self.pro.income, code)
        bs = self._fetch(self.pro.balancesheet, code)
        cf = self._fetch(self.pro.cashflow, code)
        fi = self._fetch(self.pro.fina_indicator, code)
        out: dict = {}

        period = next((_latest_end(r) for r in (inc, fi, bs, cf) if r is not None), None)
        if period:
            out["报告期"] = period

        rev = _num(inc, "revenue")
        np_ = _num(inc, "n_income_attr_p")
        if rev is not None:
            out["营收_亿"] = round(rev / _YI, 2)
        if np_ is not None:
            out["归母净利_亿"] = round(np_ / _YI, 2)
        for src, dst in [("or_yoy", "营收同比"), ("netprofit_yoy", "净利同比"),
                         ("grossprofit_margin", "毛利率"), ("roe", "ROE"),
                         ("debt_to_assets", "资产负债率")]:
            v = _num(fi, src)
            if v is not None:
                out[dst] = round(v, 2)

        ocf = _num(cf, "n_cashflow_act")
        if ocf is not None:
            out["经营现金流_亿"] = round(ocf / _YI, 2)
            if np_:   # 盈利质量:经营现金流 / 归母净利
                out["现金流净利比"] = round(ocf / np_, 2)

        gw = _num(bs, "goodwill")
        ar = _num(bs, "accounts_receiv")
        if gw is not None:
            out["商誉_亿"] = round(gw / _YI, 2)
        if ar is not None:
            out["应收账款_亿"] = round(ar / _YI, 2)
            if rev:
                out["应收营收比"] = round(ar / rev, 2)

        return out or None


def _latest_end(row):
    v = row.get("end_date")
    return str(v) if v is not None and pd.notna(v) else None
