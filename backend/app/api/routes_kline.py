from datetime import datetime, timedelta
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.api.deps import get_session
from app.data.minute_store import MinuteStore
from app.data.names import NameLookup

router = APIRouter(prefix="/api/kline", tags=["kline"])


@router.get("/{code}")
def kline(code: str, freq: str = "1min", days: int = 2,
          s: Session = Depends(get_session)):
    """只读库返回分钟线,不调 tushare(与采集守护彻底解耦,响应快)。
    库里没有则 bars=[](前端显示「采集中」)。"""
    store = MinuteStore(s)
    now = datetime.now()
    start_dt = now - timedelta(days=days)
    end_dt = now + timedelta(days=1)  # buffer,避免时区/时钟边界漏掉今天的数据
    bars = store.get_bars(code, freq, start_dt, end_dt)
    last = store.last_time(code, freq)
    return {
        "code": code,
        "name": NameLookup(s).get(code),
        "freq": freq,
        "bars": bars,
        "last_time": last.isoformat() if last else None,
    }
