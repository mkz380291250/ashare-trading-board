from datetime import date
import pandas as pd
from app.data.source import DailyBar, MarketDataSource


def _fmt(d: date) -> str:
    return d.strftime("%Y%m%d")


def _parse(s: str) -> date:
    return date(int(s[:4]), int(s[4:6]), int(s[6:8]))


class TushareSource(MarketDataSource):
    def __init__(self, pro=None, token: str | None = None):
        if pro is not None:
            self.pro = pro
        else:
            import tushare as ts
            ts.set_token(token or "")
            self.pro = ts.pro_api()

    def get_daily_bars(self, code: str, start: date, end: date) -> list[DailyBar]:
        daily = self.pro.daily(ts_code=code, start_date=_fmt(start), end_date=_fmt(end))
        adj = self.pro.adj_factor(ts_code=code, start_date=_fmt(start), end_date=_fmt(end))
        merged = daily.merge(adj[["trade_date", "adj_factor"]], on="trade_date", how="left")
        merged = merged.sort_values("trade_date")  # ascending
        bars: list[DailyBar] = []
        for _, r in merged.iterrows():
            bars.append(DailyBar(
                code=code, trade_date=_parse(str(r["trade_date"])),
                open=float(r["open"]), high=float(r["high"]), low=float(r["low"]),
                close=float(r["close"]), volume=float(r["vol"]),
                adj_factor=float(r["adj_factor"]) if pd.notna(r["adj_factor"]) else 1.0,
            ))
        return bars
