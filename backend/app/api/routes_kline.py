from datetime import datetime, timedelta
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.api.deps import get_session
from app.data.minute_store import MinuteStore
from app.data.quote_store import QuoteStore
from app.data.adjust import to_qfq
from app.data.names import NameLookup

router = APIRouter(prefix="/api/kline", tags=["kline"])

DAY_FREQS = {"day", "1d", "daily"}


def get_minute_fetcher():
    """按需采集器(腾讯)。测试里被 override 成假采集器以免联网。"""
    from app.data.minute_fetch_tencent import TencentMinuteFetcher
    return TencentMinuteFetcher()


def _daily(code: str, days: int, s: Session) -> dict:
    """日线走历史行情库 daily_quotes(全市场已有),前复权后返回。"""
    now = datetime.now()
    bars_raw = QuoteStore(s).get_bars(
        code, (now - timedelta(days=days)).date(), now.date())
    qfq = to_qfq(bars_raw)
    bars = [{"t": b.trade_date.isoformat(), "o": round(b.open, 2),
             "h": round(b.high, 2), "l": round(b.low, 2),
             "c": round(b.close, 2), "v": b.volume} for b in qfq]
    return {"code": code, "name": NameLookup(s).get(code), "freq": "day",
            "bars": bars, "last_time": bars[-1]["t"] if bars else None}


@router.get("/{code}")
def kline(code: str, freq: str = "day", days: int = 400,
          s: Session = Depends(get_session),
          fetcher=Depends(get_minute_fetcher)):
    """日线走 daily_quotes(前复权);分钟线读 minute_quotes,库里没有则当场抓一次
    (腾讯)→落库→返回,点开任意股票即时出图。"""
    if freq in DAY_FREQS:
        return _daily(code, days, s)
    store = MinuteStore(s)
    now = datetime.now()
    start_dt = now - timedelta(days=days)
    end_dt = now + timedelta(days=1)  # buffer,避免时区/时钟边界漏掉今天的数据
    bars = store.get_bars(code, freq, start_dt, end_dt)
    if not bars and fetcher is not None:
        try:
            rows = fetcher.fetch(code, freq, None, None)
            if rows:
                store.upsert(code, freq, rows)
                bars = store.get_bars(code, freq, start_dt, end_dt)
        except Exception:
            pass  # 抓取失败:退化为空,前端显示「采集中」
    last = store.last_time(code, freq)
    return {
        "code": code,
        "name": NameLookup(s).get(code),
        "freq": freq,
        "bars": bars,
        "last_time": last.isoformat() if last else None,
    }
