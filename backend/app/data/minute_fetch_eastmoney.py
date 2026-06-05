"""分钟线采集:东方财富 push2his kline(免费、免授权、无 tushare 频次限制)。

只用于分钟线;日线仍走 tushare(不改)。与 MinuteFetcher 同接口
(fetch(code, freq, start, end) -> list[dict]),可直接替换。
"""
import json
import time
import urllib.request
from datetime import datetime

# freq -> 东财 klt
_KLT = {"1min": "1", "5min": "5", "15min": "15", "30min": "30", "60min": "60"}
_FMT_OUT = "%Y-%m-%d %H:%M:%S"
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")


def secid_of(code: str) -> str:
    """600519.SH -> 1.600519;300566.SZ -> 0.300566;920128.BJ -> 0.920128。"""
    num, _, suf = code.partition(".")
    market = "1" if suf.upper() == "SH" else "0"   # SH=1,SZ/BJ=0
    return f"{market}.{num}"


# 直连东财,绕过容器的 https_proxy(代理会破坏到 push2his 的 TLS 握手)。
_DIRECT = urllib.request.build_opener(urllib.request.ProxyHandler({}))


_HDRS = {"User-Agent": _UA, "Accept": "*/*",
         "Referer": "https://quote.eastmoney.com/"}


def _default_get_json(secid: str, klt: str, lmt: int, retries: int = 3) -> dict:
    url = ("https://push2his.eastmoney.com/api/qt/stock/kline/get?"
           f"secid={secid}&fields1=f1,f2,f3"
           "&fields2=f51,f52,f53,f54,f55,f56,f57"
           f"&klt={klt}&fqt=1&end=20500101&lmt={lmt}")
    last = None
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers=_HDRS)
            with _DIRECT.open(req, timeout=20) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as e:   # 限流/断连:退避重试
            last = e
            time.sleep(1.5 * (i + 1))
    raise last


def _parse_dt(s: str) -> datetime:
    s = s.strip()
    fmt = "%Y-%m-%d %H:%M" if len(s) <= 16 else "%Y-%m-%d %H:%M:%S"
    return datetime.strptime(s, fmt)


class EastMoneyMinuteFetcher:
    """get_json(secid, klt, lmt) -> dict 可注入以便测试/换源。出错返 []。"""

    def __init__(self, get_json=_default_get_json, limiter=None, lmt: int = 240):
        self.get_json = get_json
        self.limiter = limiter
        self.lmt = lmt

    def fetch(self, code: str, freq: str, start, end) -> list[dict]:
        klt = _KLT.get(freq)
        if klt is None:
            return []
        if self.limiter is not None:
            self.limiter.acquire()
        try:
            data = self.get_json(secid_of(code), klt, self.lmt)
        except Exception:
            return []
        d = (data or {}).get("data") or {}
        klines = d.get("klines") or []
        if not klines:
            return []
        s_dt = _parse_dt(start) if start else None
        e_dt = _parse_dt(end) if end else None
        rows: list[dict] = []
        for line in klines:
            parts = line.split(",")
            if len(parts) < 6:
                continue
            t = _parse_dt(parts[0])
            if s_dt and t <= s_dt:      # 增量:严格晚于库内 last_time
                continue
            if e_dt and t > e_dt:
                continue
            amount = float(parts[6]) if len(parts) > 6 and parts[6] else None
            rows.append({
                "code": code, "freq": freq, "trade_time": t,
                "open": float(parts[1]), "close": float(parts[2]),   # EM: open,close,high,low
                "high": float(parts[3]), "low": float(parts[4]),
                "vol": float(parts[5]), "amount": amount,
            })
        return rows
