from abc import ABC, abstractmethod
from app.discovery.snapshot import StockData


class SignalProvider(ABC):
    @abstractmethod
    def compute(self, snapshot: dict[str, StockData]) -> dict[str, dict[str, float]]:
        """Return {factor_name: {code: raw_value}}."""
        ...


class MomentumProvider(SignalProvider):
    HIGH_LOOKBACK = 20

    def compute(self, snapshot: dict[str, StockData]) -> dict[str, dict[str, float]]:
        out: dict[str, dict[str, float]] = {
            "mom_5d": {}, "turnover": {}, "vol_ratio": {}, "breakout": {}}
        for code, s in snapshot.items():
            if len(s.closes) >= 6 and s.closes[-6] != 0:
                out["mom_5d"][code] = s.closes[-1] / s.closes[-6] - 1.0
            if s.closes and s.highs:
                hi = max(s.highs[-self.HIGH_LOOKBACK:])
                if hi != 0:
                    out["breakout"][code] = s.closes[-1] / hi
            if s.turnover is not None:
                out["turnover"][code] = s.turnover
            if s.vol_ratio is not None:
                out["vol_ratio"][code] = s.vol_ratio
        return out
