from datetime import datetime
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.db.models import MinuteQuote


class MinuteStore:
    """库内分钟线读写。一张 minute_quotes 表用 freq 列容纳多周期。"""

    def __init__(self, session: Session):
        self.s = session

    def upsert(self, code: str, freq: str, rows: list[dict]) -> None:
        for r in rows:
            # code/freq 以参数为准,避免行内残留值串档
            self.s.merge(MinuteQuote(**{**r, "code": code, "freq": freq}))
        self.s.commit()

    def get_bars(self, code: str, freq: str,
                 start_dt: datetime, end_dt: datetime) -> list[dict]:
        rows = self.s.scalars(
            select(MinuteQuote).where(
                MinuteQuote.code == code,
                MinuteQuote.freq == freq,
                MinuteQuote.trade_time >= start_dt,
                MinuteQuote.trade_time <= end_dt,
            ).order_by(MinuteQuote.trade_time)
        ).all()
        return [{"t": r.trade_time, "o": r.open, "h": r.high, "l": r.low,
                 "c": r.close, "v": r.vol} for r in rows]

    def last_time(self, code: str, freq: str) -> datetime | None:
        return self.s.scalars(
            select(MinuteQuote.trade_time).where(
                MinuteQuote.code == code, MinuteQuote.freq == freq,
            ).order_by(MinuteQuote.trade_time.desc()).limit(1)
        ).first()
