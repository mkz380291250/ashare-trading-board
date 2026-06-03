from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class ResearchItem:
    title: str
    text: str
    date: str
    rating: str | None = None
    target_price: float | None = None
    source: str = ""


class ResearchSource(ABC):
    @abstractmethod
    def fetch(self, code: str, as_of: date) -> list[ResearchItem]:
        ...


def _rows(df):
    """tushare 返回 DataFrame;统一成 list[dict]。None/空 → []。"""
    if df is None:
        return []
    try:
        if getattr(df, "empty", False):
            return []
        return df.to_dict("records")
    except Exception:
        return []


class TushareResearchSource(ResearchSource):
    def __init__(self, pro, limiter=None):
        self.pro = pro
        self.limiter = limiter

    def fetch(self, code: str, as_of: date) -> list[ResearchItem]:
        items: list[ResearchItem] = []
        if self.limiter:
            self.limiter.acquire()
        try:
            for r in _rows(self.pro.report_rc(ts_code=code)):
                items.append(ResearchItem(
                    title=str(r.get("report_title") or ""),
                    text=str(r.get("report_title") or ""),
                    date=str(r.get("report_date") or ""),
                    rating=r.get("rating"),
                    target_price=r.get("tp_eps"),
                    source="tushare:report_rc"))
        except Exception:
            pass
        if self.limiter:
            self.limiter.acquire()
        try:
            for r in _rows(self.pro.news(src="sina")):
                items.append(ResearchItem(
                    title="", text=str(r.get("content") or ""),
                    date=str(r.get("datetime") or ""),
                    source="tushare:news"))
        except Exception:
            pass
        return items
