from datetime import date
import pandas as pd


def _fmt(d: date) -> str:
    return d.strftime("%Y%m%d")


class MarketFetcher:
    """Fetch + merge one trade date's whole-market quotes. tushare calls are
    routed through `limiter.acquire()` (a RateLimiter or compatible)."""

    def __init__(self, pro, limiter):
        self.pro = pro
        self.limiter = limiter

    def fetch_day(self, trade_date: date) -> list[dict]:
        ds = _fmt(trade_date)
        self.limiter.acquire(); daily = self.pro.daily(trade_date=ds)
        self.limiter.acquire(); basic = self.pro.daily_basic(trade_date=ds)
        self.limiter.acquire(); adj = self.pro.adj_factor(trade_date=ds)
        if daily is None or daily.empty:
            return []
        if adj is None or adj.empty or "adj_factor" not in adj.columns:
            # tushare 偶发返回空表(2026-09-15 追溯 2015-07 时撞到过):重试一次,仍空则报错
            # 让调用方跳过这一天,绝不能默默写 1.0 的假因子
            self.limiter.acquire(); adj = self.pro.adj_factor(trade_date=ds)
            if adj is None or adj.empty or "adj_factor" not in adj.columns:
                raise ValueError(f"adj_factor empty for {ds}")
        if basic is None or basic.empty:
            basic = pd.DataFrame({"ts_code": []})

        # daily_basic shares column names with daily (close/open/...); take only
        # the metric columns we need so the merge does not rename `close` etc.
        basic_cols = ["ts_code", "turnover_rate", "volume_ratio",
                      "circ_mv", "total_mv", "pe", "pb"]
        basic = basic[[c for c in basic_cols if c in basic.columns]]
        m = daily.merge(basic, on="ts_code", how="left")
        m = m.merge(adj[["ts_code", "adj_factor"]], on="ts_code", how="left")
        rows: list[dict] = []
        for _, r in m.iterrows():
            rows.append({
                "code": r["ts_code"], "trade_date": trade_date,
                "open": _f(r, "open"), "high": _f(r, "high"),
                "low": _f(r, "low"), "close": _f(r, "close"),
                "pre_close": _f(r, "pre_close"), "vol": _f(r, "vol"),
                "amount": _f(r, "amount"),
                "adj_factor": _f(r, "adj_factor", 1.0),
                "turnover_rate": _f(r, "turnover_rate"),
                "volume_ratio": _f(r, "volume_ratio"),
                "circ_mv": _f(r, "circ_mv"), "total_mv": _f(r, "total_mv"),
                "pe": _f(r, "pe"), "pb": _f(r, "pb"),
            })
        return rows


def _f(row, key: str, default=None):
    if key not in row or pd.isna(row[key]):
        return default
    return float(row[key])
