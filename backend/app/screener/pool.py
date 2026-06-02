import json
from datetime import date
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.db.models import WatchPoolEntry
from app.data.source import DailyBar
from app.screener.filters import forward_return

_OFFSETS = {"ret_t1": 1, "ret_t3": 3, "ret_t5": 5, "ret_t10": 10}


class WatchPool:
    def __init__(self, session: Session):
        self.s = session

    def get(self, code: str, on: date) -> WatchPoolEntry | None:
        return self.s.get(WatchPoolEntry, (code, on))

    def add(self, code: str, theme: str, on: date, entry_close: float, trigger: dict) -> None:
        if self.get(code, on) is not None:
            return                      # idempotent: keep the first selection
        self.s.add(WatchPoolEntry(code=code, first_selected_on=on, theme=theme,
                                  entry_close=entry_close, trigger=json.dumps(trigger)))
        self.s.commit()

    def update_forward_returns(self, code: str, on: date, bars: list[DailyBar]) -> None:
        entry = self.get(code, on)
        if entry is None:
            return
        closes = [b.close for b in bars if b.trade_date >= on]  # index 0 == entry day
        for field, n in _OFFSETS.items():
            fut = closes[n] if len(closes) > n else None
            setattr(entry, field, forward_return(entry.entry_close, fut))
        entry.last_updated = bars[-1].trade_date if bars else on
        self.s.commit()

    def list(self) -> list[WatchPoolEntry]:
        return list(self.s.scalars(
            select(WatchPoolEntry).order_by(WatchPoolEntry.first_selected_on.desc())
        ).all())
