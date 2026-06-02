from abc import ABC, abstractmethod


class PriceProvider(ABC):
    @abstractmethod
    def latest_close(self, code: str) -> float: ...


class DictPriceProvider(PriceProvider):
    def __init__(self, prices: dict[str, float]):
        self._prices = prices

    def latest_close(self, code: str) -> float:
        return self._prices[code]
