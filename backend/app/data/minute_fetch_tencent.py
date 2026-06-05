"""分钟线采集:腾讯行情 ifzq.gtimg.cn mkline(免费、免授权、无 tushare 频次限制)。

只用于分钟线;日线仍走 tushare(不改)。与 MinuteFetcher / EastMoneyMinuteFetcher
同接口(fetch(code, freq, start, end) -> list[dict]),可直接替换。

为什么用腾讯:东财 push2his 被容器 egress 反爬封死(RemoteDisconnected);新浪
getKLineData 干净但最小只到 5 分钟、缺 1 分钟。腾讯 mkline 覆盖全部 m1/m5/m15/m30/m60,
是开源圈(akshare 等)的通行备选源。
"""
import json
import time
import urllib.request
from datetime import datetime

# freq -> 腾讯 mkline 周期键
_FREQ = {"1min": "m1", "5min": "m5", "15min": "m15", "30min": "m30", "60min": "m60"}
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")


def tencent_symbol(code: str) -> str:
    """600519.SH -> sh600519;300566.SZ -> sz300566;920128.BJ -> bj920128。"""
    num, _, suf = code.partition(".")
    return f"{suf.lower()}{num}"


# 直连(代理会破坏部分行情站的 TLS;直连/代理实测均通,直连更稳)。
_DIRECT = urllib.request.build_opener(urllib.request.ProxyHandler({}))
_HDRS = {"User-Agent": _UA, "Accept": "*/*",
         "Referer": "https://gu.qq.com/"}


def _default_get_json(symbol: str, freq_key: str, lmt: int, retries: int = 3) -> dict:
    url = ("https://ifzq.gtimg.cn/appstock/app/kline/mkline?"
           f"param={symbol},{freq_key},,{lmt}")
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
    if s.isdigit():                       # 腾讯:YYYYMMDDHHMM
        return datetime.strptime(s, "%Y%m%d%H%M")
    fmt = "%Y-%m-%d %H:%M" if len(s) <= 16 else "%Y-%m-%d %H:%M:%S"
    return datetime.strptime(s, fmt)


class TencentMinuteFetcher:
    """get_json(symbol, freq_key, lmt) -> dict 可注入以便测试/换源。出错返 []。"""

    def __init__(self, get_json=_default_get_json, limiter=None, lmt: int = 320):
        self.get_json = get_json
        self.limiter = limiter
        self.lmt = lmt

    def fetch(self, code: str, freq: str, start, end) -> list[dict]:
        freq_key = _FREQ.get(freq)
        if freq_key is None:
            return []
        if self.limiter is not None:
            self.limiter.acquire()
        symbol = tencent_symbol(code)
        try:
            data = self.get_json(symbol, freq_key, self.lmt)
        except Exception:
            return []
        node = ((data or {}).get("data") or {}).get(symbol) or {}
        klines = node.get(freq_key) or []
        if not klines:
            return []
        s_dt = _parse_dt(start) if start else None
        e_dt = _parse_dt(end) if end else None
        rows: list[dict] = []
        for k in klines:
            if not isinstance(k, (list, tuple)) or len(k) < 6:
                continue
            t = _parse_dt(str(k[0]))
            if s_dt and t <= s_dt:      # 增量:严格晚于库内 last_time
                continue
            if e_dt and t > e_dt:
                continue
            rows.append({
                "code": code, "freq": freq, "trade_time": t,
                "open": float(k[1]), "close": float(k[2]),   # 腾讯: open,close,high,low
                "high": float(k[3]), "low": float(k[4]),
                "vol": float(k[5]), "amount": None,
            })
        return rows
