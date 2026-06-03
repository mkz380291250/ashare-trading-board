from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class Earnings:
    np_yoy: float    # net profit YoY %
    rev_yoy: float   # revenue YoY %


def passes_earnings(e: "Earnings | None", min_np_yoy: float = 20.0) -> bool:
    if e is None:
        return False
    return e.np_yoy >= min_np_yoy and e.rev_yoy > 0.0


class EarningsSource(ABC):
    @abstractmethod
    def latest(self, code: str) -> "Earnings | None": ...


class TushareEarningsSource(EarningsSource):
    def __init__(self, pro):
        self.pro = pro

    def latest(self, code: str) -> "Earnings | None":
        df = self.pro.fina_indicator(ts_code=code)
        if df is None or df.empty:
            return None
        df = df.sort_values("end_date")
        r = df.iloc[-1]
        import pandas as pd
        np_yoy = float(r["netprofit_yoy"]) if pd.notna(r.get("netprofit_yoy")) else 0.0
        rev_yoy = float(r["or_yoy"]) if pd.notna(r.get("or_yoy")) else 0.0
        return Earnings(np_yoy=np_yoy, rev_yoy=rev_yoy)
