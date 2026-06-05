from datetime import datetime, timedelta
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.api.deps import get_session
from app.data.minute_store import MinuteStore
from app.data.names import NameLookup

router = APIRouter(prefix="/api/kline", tags=["kline"])


def get_minute_fetcher():
    """按需采集器(腾讯)。测试里被 override 成假采集器以免联网。"""
    from app.data.minute_fetch_tencent import TencentMinuteFetcher
    return TencentMinuteFetcher()


@router.get("/{code}")
def kline(code: str, freq: str = "1min", days: int = 2,
          s: Session = Depends(get_session),
          fetcher=Depends(get_minute_fetcher)):
    """读库返回分钟线。库里没有该股该周期数据时,当场抓一次(腾讯)→落库→返回,
    点开任意股票都能即时出图;后续由采集守护增量更新。"""
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
