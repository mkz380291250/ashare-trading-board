"""腾讯行情日线 + 批量快照(免费、免授权;容器 egress 已验证可达,东财 push2 会被封)。
用途:① 北交所(.BJ)日线(baostock 不覆盖);② baostock 故障时沪深全市场兜底。
- fqkline day 原始价 + hfq 后复权价:因子只在除权日按 (hfq/raw) 比值的跳变更新,
  其余日期沿用前一日(避免 3 位小数舍入带来的逐日抖动)。
- qt.gtimg.cn 批量快照给"最新交易日"的成交额/换手/pe/pb/市值;更早的日期这些
  字段取不到:市值按库内流通股本外推、pe/pb 按价格比例外推、成交额/换手留空。
"""
from __future__ import annotations
import json
import threading
import time
from datetime import date

import requests

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
_HDRS = {"User-Agent": _UA, "Referer": "https://gu.qq.com/"}
_TLS = threading.local()
_LIMITER = None            # 全局限速(所有线程共享),None=不限


def set_rate_limit(max_per_min: int | None) -> None:
    """腾讯 WAF 对 ~30 req/s 的突发直接封 501(约数分钟);默认 480/min(8/s)。"""
    global _LIMITER
    if max_per_min:
        from app.data.rate_limiter import RateLimiter
        _LIMITER = RateLimiter(max_calls=max_per_min, period_s=60.0)
    else:
        _LIMITER = None


_LOCK = threading.Lock()


def _session() -> requests.Session:
    """每线程一个长连接 Session(逐请求新建 TLS 握手 + 加载证书会把吞吐拖到 2 只/秒);
    trust_env=False 直连,绕过容器的 https_proxy。"""
    s = getattr(_TLS, "session", None)
    if s is None:
        s = requests.Session()
        s.trust_env = False
        s.headers.update(_HDRS)
        _TLS.session = s
    return s


def tx_symbol(code: str) -> str:
    """600519.SH -> sh600519;920128.BJ -> bj920128"""
    num, _, suf = code.partition(".")
    return f"{suf.lower()}{num}"


def _get(url: str, retries: int = 3, timeout: float = 20.0, encoding="utf-8") -> str:
    last = None
    for i in range(retries):
        try:
            if _LIMITER is not None:
                with _LOCK:
                    _LIMITER.acquire()
            resp = _session().get(url, timeout=timeout)
            resp.raise_for_status()
            resp.encoding = encoding
            return resp.text
        except Exception as e:      # noqa: BLE001 — 限流/断连退避重试
            last = e
            _TLS.session = None
            time.sleep(5.0 * (i + 1))
    raise last


set_rate_limit(480)


def klines(code: str, start: date, end: date, fq: str = "") -> list[list]:
    """fq: '' 原始 | 'hfq' 后复权。返回 [[date, open, close, high, low, vol(手), {除权信息}?], ...]"""
    sym = tx_symbol(code)
    n = max((end - start).days + 5, 10)
    url = ("https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?"
           f"param={sym},day,{start.isoformat()},{end.isoformat()},{n},{fq}")
    data = json.loads(_get(url))
    d = ((data or {}).get("data") or {}).get(sym) or {}
    key = "hfqday" if fq == "hfq" else "day"
    return d.get(key) or []


def quotes(codes: list[str], batch: int = 200) -> dict[str, dict]:
    """批量快照 → {code: {date, open/high/low/close/pre_close, vol(手), amount(千元),
    turnover_rate, pe, pb, circ_mv(万), total_mv(万)}}。date 是该股最后成交日(停牌股是旧日期)。"""
    out: dict[str, dict] = {}
    for i in range(0, len(codes), batch):
        chunk = codes[i:i + batch]
        txt = _get("https://qt.gtimg.cn/q=" + ",".join(tx_symbol(c) for c in chunk),
                   encoding="gbk")
        by_sym = {tx_symbol(c): c for c in chunk}
        for line in txt.split("\n"):
            if "=" not in line:
                continue
            name, _, body = line.partition("=")
            sym = name.strip().replace("v_", "")
            f = body.strip().strip('";').split("~")
            if sym not in by_sym or len(f) < 47 or not f[30]:
                continue
            out[by_sym[sym]] = {
                "date": date(int(f[30][:4]), int(f[30][4:6]), int(f[30][6:8])),
                "open": _f(f[5]), "high": _f(f[33]), "low": _f(f[34]),
                "close": _f(f[3]), "pre_close": _f(f[4]),   # 昨收是除权后参考价
                # 手;科创板(688/689)腾讯快照给的是"股",除以 100 对齐
                "vol": _f(f[36], 0.01 if by_sym[sym].startswith("68") else 1.0),
                "amount": _f(f[37], 10.0),          # 万元 → 千元
                "turnover_rate": _f(f[38]),
                "pe": _f(f[39]), "pb": _f(f[46]),
                "circ_mv": _f(f[44], 1e4), "total_mv": _f(f[45], 1e4),   # 亿 → 万
            }
    return out


def _f(v, scale: float = 1.0):
    try:
        return float(v) * scale if v not in ("", None) else None
    except (TypeError, ValueError):
        return None
