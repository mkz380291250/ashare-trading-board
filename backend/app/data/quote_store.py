from datetime import date
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.db.models import DailyQuote, IngestedDay
from app.data.source import DailyBar


class QuoteStore:
    def __init__(self, session: Session):
        self.s = session

    def upsert_day(self, trade_date: date, rows: list[dict]) -> None:
        for r in rows:
            self.s.merge(DailyQuote(**r))   # PK (code, trade_date) -> insert or update
        self.s.commit()

    def mark_ingested(self, trade_date: date) -> None:
        self.s.merge(IngestedDay(trade_date=trade_date))
        self.s.commit()

    def ingested_dates(self) -> set[date]:
        return set(self.s.scalars(select(IngestedDay.trade_date)).all())

    def get_market_on(self, trade_date: date) -> list[DailyQuote]:
        return list(self.s.scalars(
            select(DailyQuote).where(DailyQuote.trade_date == trade_date)
        ).all())

    def trading_dates(self, end: date, limit: int) -> list[date]:
        rows = self.s.scalars(
            select(DailyQuote.trade_date).where(DailyQuote.trade_date <= end)
            .distinct().order_by(DailyQuote.trade_date.desc()).limit(limit)
        ).all()
        return sorted(rows)

    def get_range(self, start: date, end: date) -> list[DailyQuote]:
        return list(self.s.scalars(
            select(DailyQuote).where(
                DailyQuote.trade_date >= start, DailyQuote.trade_date <= end
            ).order_by(DailyQuote.code, DailyQuote.trade_date)
        ).all())

    def get_bars(self, code: str, start: date, end: date) -> list[DailyBar]:
        rows = self.s.scalars(
            select(DailyQuote).where(
                DailyQuote.code == code,
                DailyQuote.trade_date >= start,
                DailyQuote.trade_date <= end,
            ).order_by(DailyQuote.trade_date)
        ).all()
        return [DailyBar(code=r.code, trade_date=r.trade_date, open=r.open,
                         high=r.high, low=r.low, close=r.close, volume=r.vol,
                         adj_factor=r.adj_factor) for r in rows]
