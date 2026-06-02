from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class StockData:
    code: str
    closes: list[float]   # ascending, ending on as_of
    highs: list[float]    # ascending, ending on as_of
    turnover: float | None
    vol_ratio: float | None


class MarketHistory(ABC):
    @abstractmethod
    def load(self, as_of: date, window: int = 20) -> dict[str, StockData]:
        ...


class QuoteStoreMarketHistory(MarketHistory):
    def __init__(self, store):
        self.store = store

    def load(self, as_of: date, window: int = 20) -> dict[str, StockData]:
        dates = self.store.trading_dates(as_of, window)
        if not dates or dates[-1] != as_of:
            return {}
        rows = self.store.get_range(dates[0], as_of)
        by_code: dict[str, list] = {}
        for r in rows:
            by_code.setdefault(r.code, []).append(r)
        out: dict[str, StockData] = {}
        for code, rs in by_code.items():
            rs.sort(key=lambda r: r.trade_date)
            if rs[-1].trade_date != as_of:
                continue  # not trading on as_of
            out[code] = StockData(
                code=code,
                closes=[r.close for r in rs],
                highs=[r.high for r in rs],
                turnover=rs[-1].turnover_rate,
                vol_ratio=rs[-1].volume_ratio,
            )
        return out
