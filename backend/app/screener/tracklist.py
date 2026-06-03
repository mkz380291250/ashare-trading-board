from datetime import date
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.db.models import TrackEntry
from app.data.source import DailyBar
from app.screener.filters import forward_return

_OFFSETS = {"ret_t1": 1, "ret_t3": 3, "ret_t5": 5, "ret_t10": 10}


class Tracker:
    def __init__(self, session: Session):
        self.s = session

    def get(self, code: str, on: date) -> TrackEntry | None:
        return self.s.get(TrackEntry, (code, on))

    def add(self, codes_with_names: list[tuple[str, str]], on: date,
            closes: dict[str, float]) -> list[TrackEntry]:
        """写入条目;跳过无收盘价的代码;同 (code,on) 已存在则保留首次。"""
        added: list[TrackEntry] = []
        for code, name in codes_with_names:
            if code not in closes:
                continue
            if self.get(code, on) is not None:
                continue
            e = TrackEntry(code=code, added_on=on, name=name,
                           entry_close=closes[code])
            self.s.add(e)
            added.append(e)
        self.s.commit()
        return added

    def update_metrics(self, code: str, on: date, bars: list[DailyBar]) -> None:
        e = self.get(code, on)
        if e is None:
            return
        closes = [b.close for b in bars if b.trade_date >= on]  # index0 == 入选日
        if not closes:
            return
        for field, n in _OFFSETS.items():
            fut = closes[n] if len(closes) > n else None
            setattr(e, field, forward_return(e.entry_close, fut))
        last = closes[-1]
        e.last_close = last
        e.ret_since = last / e.entry_close - 1.0
        future = closes[1:]
        if future:
            e.max_gain = max(c / e.entry_close - 1.0 for c in future)
            peak = closes[0]
            dd = 0.0
            for c in closes[1:]:
                peak = max(peak, c)
                dd = min(dd, c / peak - 1.0)
            e.max_drawdown = dd
        else:
            e.max_gain = 0.0
            e.max_drawdown = 0.0
        e.last_updated = bars[-1].trade_date if bars else on
        self.s.commit()

    def list(self) -> list[TrackEntry]:
        return list(self.s.scalars(
            select(TrackEntry).order_by(TrackEntry.added_on.desc(),
                                        TrackEntry.code)
        ).all())

    def remove(self, code: str, on: date) -> None:
        e = self.get(code, on)
        if e is not None:
            self.s.delete(e)
            self.s.commit()
