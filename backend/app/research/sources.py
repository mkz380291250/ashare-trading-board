from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date, timedelta


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
    """券商研报评级/目标价 (tushare report_rc, per-stock & structured).

    report_rc 不带日期会返回该股全部历史(数千条)且限频 1次/分钟,故只取
    最近 recent_days 窗口、按 report_date 倒序截断 max_items 条。tushare 的
    news 接口是全市场新闻流(不按 ts_code 过滤),对个股是噪声,这里不用;
    个股新闻由 EastMoneyNewsSource 提供。
    """

    def __init__(self, pro, limiter=None, recent_days: int = 120,
                 max_items: int = 25):
        self.pro = pro
        self.limiter = limiter
        self.recent_days = recent_days
        self.max_items = max_items

    def fetch(self, code: str, as_of: date) -> list[ResearchItem]:
        if self.limiter:
            self.limiter.acquire()
        start = (as_of - timedelta(days=self.recent_days)).strftime("%Y%m%d")
        try:
            rows = _rows(self.pro.report_rc(ts_code=code, start_date=start))
        except Exception:
            return []
        rows.sort(key=lambda r: str(r.get("report_date") or ""), reverse=True)
        items: list[ResearchItem] = []
        for r in rows[: self.max_items]:
            items.append(ResearchItem(
                title=str(r.get("report_title") or ""),
                text=str(r.get("report_title") or ""),
                date=str(r.get("report_date") or ""),
                rating=r.get("rating"),
                target_price=r.get("tp_eps"),
                source="tushare:report_rc"))
        return items


def _em_default_fetch(code: str, page_size: int = 8,
                      timeout: float = 12.0) -> list[dict]:
    """EastMoney 个股新闻 (search-api-web, JSONP). 返回 [{title, content, date}].
    失败抛异常,由 EastMoneyNewsSource 吞掉返 []。容器 egress 已验证可达
    (2026-06-03)。preTag/postTag 置空,标题正文无高亮标签。"""
    import json
    import requests
    num = code.split(".")[0]  # 600519.SH -> 600519
    param = json.dumps({
        "uid": "", "keyword": num, "type": ["cmsArticleWebOld"],
        "client": "web", "clientType": "web", "clientVersion": "curr",
        "param": {"cmsArticleWebOld": {
            "searchScope": "default", "sort": "default",
            "pageIndex": 1, "pageSize": page_size,
            "preTag": "", "postTag": ""}}})
    r = requests.get(
        "https://search-api-web.eastmoney.com/search/jsonp",
        params={"cb": "x", "param": param},
        headers={"User-Agent": "Mozilla/5.0",
                 "Referer": "https://so.eastmoney.com/"},
        timeout=timeout)
    r.raise_for_status()
    text = r.text
    body = text[text.index("(") + 1: text.rindex(")")]  # 去 jsonp 外壳
    data = json.loads(body)
    arts = (data.get("result") or {}).get("cmsArticleWebOld") or []
    return [{"title": a.get("title", ""), "content": a.get("content", ""),
             "date": a.get("date", "")} for a in arts]


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
