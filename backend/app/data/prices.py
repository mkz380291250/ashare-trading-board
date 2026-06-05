from abc import ABC, abstractmethod
from datetime import date
from app.data.quote_store import QuoteStore


class PriceProvider(ABC):
    @abstractmethod
    def latest_close(self, code: str) -> float: ...


class DictPriceProvider(PriceProvider):
    def __init__(self, prices: dict[str, float]):
        self._prices = prices

    def latest_close(self, code: str) -> float:
        return self._prices[code]


def latest_close(store: QuoteStore, code: str, on: date) -> float | None:
    start = date(on.year - 1, on.month, on.day)
    bars = store.get_bars(code, start, on)
    return bars[-1].close if bars else None
