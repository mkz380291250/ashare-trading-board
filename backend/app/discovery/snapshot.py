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
