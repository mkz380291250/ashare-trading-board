from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class DailyBar:
    code: str
    trade_date: date
    open: float
    high: float
    low: float
    close: float
    volume: float
    adj_factor: float  # raw (non-adjusted) prices + factor; qfq/hfq derived later


class MarketDataSource(ABC):
    @abstractmethod
    def get_daily_bars(self, code: str, start: date, end: date) -> list[DailyBar]:
        ...
