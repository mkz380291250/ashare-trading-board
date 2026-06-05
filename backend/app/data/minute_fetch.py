from datetime import datetime
import pandas as pd

FREQS = ("1min", "5min", "15min", "30min", "60min")


def _parse_dt(s: str) -> datetime:
    return datetime.strptime(s.strip(), "%Y-%m-%d %H:%M:%S")


class MinuteFetcher:
    """调 tushare stk_mins 拉分钟线,走全局 RateLimiter(1,60)。出错返 []。"""

    def __init__(self, pro, limiter):
        self.pro = pro
        self.limiter = limiter

    def fetch(self, code: str, freq: str, start, end) -> list[dict]:
        self.limiter.acquire()
        try:
            df = self.pro.stk_mins(ts_code=code, freq=freq,
                                   start_date=start, end_date=end)
        except Exception:
            return []  # 限频/网络错误:不抛,留给下一轮
        if df is None or len(df) == 0:
            return []
        rows: list[dict] = []
        for _, r in df.iterrows():
            amount = r.get("amount") if hasattr(r, "get") else None
            rows.append({
                "code": code, "freq": freq,
                "trade_time": _parse_dt(str(r["trade_time"])),
                "open": float(r["open"]), "high": float(r["high"]),
                "low": float(r["low"]), "close": float(r["close"]),
                "vol": float(r["vol"]),
                "amount": float(amount) if pd.notna(amount) else None,
            })
        return rows
