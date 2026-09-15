"""baostock 季频财务数据(替代 tushare fina_indicator / 三大报表,2026-09):
同时实现 EarningsSource.latest(code) 与 FinancialsSource.summary(code) 两个接口,
一次拉最近可用季度的 profit/growth/balance/cash_flow 四张表,失败返 None 不抛。
- 净利同比 = growth.YOYPNI(归母净利润同比,小数)×100
- 营收同比 = profit.MBRevenue 本期 / 去年同期 - 1(baostock 无现成字段)
- 经营现金流 = CFOToNP × netProfit(baostock 只给比率)
- 商誉/应收 baostock 没有,摘要里省略。
"""
from __future__ import annotations
from datetime import date
import pandas as pd

from app.data.baostock_source import BaostockSource, to_bs_code
from app.screener.earnings import Earnings, EarningsSource

_YI = 1e8


def _quarters(today: date, n: int = 5) -> list[tuple[int, int]]:
    """从今天往前数 n 个"可能已披露"的报告期 (year, quarter),最近在前。"""
    y, q = today.year, (today.month - 1) // 3   # 当季未披露,从上季开始
    out = []
    for _ in range(n):
        if q == 0:
            y, q = y - 1, 4
        out.append((y, q))
        q -= 1
    return out


def _num(df: pd.DataFrame | None, key: str) -> float | None:
    if df is None or df.empty or key not in df.columns:
        return None
    v = df.iloc[-1][key]
    if v is None or v == "" or pd.isna(v):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


class BaostockFinancials(EarningsSource):
    def __init__(self, src: BaostockSource | None = None, today=None):
        self.src = src or BaostockSource()
        self.today = today
        self._cache: dict[str, dict | None] = {}

    def _q(self, fn, **kw) -> pd.DataFrame | None:
        try:
            self.src._ensure_login()
            return self.src._query(fn(**kw))
        except Exception:      # noqa: BLE001 — 单表失败不影响其余
            return None

    def _load(self, code: str) -> dict | None:
        if code in self._cache:
            return self._cache[code]
        bs_code = to_bs_code(code)
        bs = self.src.bs
        data = None
        for y, q in _quarters(self.today or date.today()):
            profit = self._q(bs.query_profit_data, code=bs_code, year=y, quarter=q)
            if profit is None or profit.empty:
                continue
            data = {
                "year": y, "quarter": q, "profit": profit,
                "growth": self._q(bs.query_growth_data, code=bs_code, year=y, quarter=q),
                "balance": self._q(bs.query_balance_data, code=bs_code, year=y, quarter=q),
                "cash": self._q(bs.query_cash_flow_data, code=bs_code, year=y, quarter=q),
                "profit_prev": self._q(bs.query_profit_data, code=bs_code, year=y - 1, quarter=q),
            }
            break
        self._cache[code] = data
        return data

    # EarningsSource
    def latest(self, code: str) -> Earnings | None:
        d = self._load(code)
        if d is None:
            return None
        np_yoy = _num(d["growth"], "YOYPNI")
        rev, rev_prev = _num(d["profit"], "MBRevenue"), _num(d["profit_prev"], "MBRevenue")
        rev_yoy = (rev / rev_prev - 1) * 100 if (rev is not None and rev_prev) else None
        if np_yoy is None and rev_yoy is None:
            return None
        return Earnings(np_yoy=(np_yoy or 0.0) * 100 if np_yoy is not None else 0.0,
                        rev_yoy=rev_yoy if rev_yoy is not None else 0.0)

    # FinancialsSource-compatible
    def summary(self, code: str) -> dict | None:
        d = self._load(code)
        if d is None:
            return None
        out: dict = {}
        stat = None
        if d["profit"] is not None and "statDate" in d["profit"].columns:
            stat = str(d["profit"].iloc[-1]["statDate"])
        if stat:
            out["报告期"] = stat.replace("-", "")
        rev = _num(d["profit"], "MBRevenue")
        np_ = _num(d["profit"], "netProfit")
        if rev is not None:
            out["营收_亿"] = round(rev / _YI, 2)
        if np_ is not None:
            out["归母净利_亿"] = round(np_ / _YI, 2)
        e = self.latest(code)
        if e is not None:
            rev_prev = _num(d["profit_prev"], "MBRevenue")
            if rev is not None and rev_prev:
                out["营收同比"] = round(e.rev_yoy, 2)
            if _num(d["growth"], "YOYPNI") is not None:
                out["净利同比"] = round(e.np_yoy, 2)
        for src_df, key, dst, scale in [
                (d["profit"], "gpMargin", "毛利率", 100), (d["profit"], "roeAvg", "ROE", 100),
                (d["balance"], "liabilityToAsset", "资产负债率", 100)]:
            v = _num(src_df, key)
            if v is not None:
                out[dst] = round(v * scale, 2)
        cfo_np = _num(d["cash"], "CFOToNP")
        if cfo_np is not None:
            out["现金流净利比"] = round(cfo_np, 2)
            if np_ is not None:
                out["经营现金流_亿"] = round(cfo_np * np_ / _YI, 2)
        return out or None

    def close(self):
        self.src.close()
