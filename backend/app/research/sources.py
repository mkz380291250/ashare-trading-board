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


def _em_default_fetch(code: str) -> list[dict]:
    """生产用:requests 抓 eastmoney 个股资讯。失败抛异常由调用方吞。
    (端点细节留待联调;沿用 screener 的 requests+重试模式。)"""
    raise NotImplementedError("wire real eastmoney endpoint during smoke task")


class EastMoneyNewsSource(ResearchSource):
    def __init__(self, fetch_fn=_em_default_fetch):
        self.fetch_fn = fetch_fn

    def fetch(self, code: str, as_of: date) -> list[ResearchItem]:
        try:
            rows = self.fetch_fn(code) or []
        except Exception:
            return []
        return [ResearchItem(
            title=str(r.get("title") or ""), text=str(r.get("content") or ""),
            date=str(r.get("date") or ""), source="eastmoney") for r in rows]


class CompositeSource(ResearchSource):
    def __init__(self, sources: list[ResearchSource]):
        self.sources = sources

    def fetch(self, code: str, as_of: date) -> list[ResearchItem]:
        seen: set[tuple] = set()
        out: list[ResearchItem] = []
        for s in self.sources:
            for it in s.fetch(code, as_of):
                key = (it.title, it.text)
                if key in seen:
                    continue
                seen.add(key)
                out.append(it)
        return out
