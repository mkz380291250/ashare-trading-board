from datetime import date
from app.research.sources import ResearchItem, TushareResearchSource


class FakePro:
    """模拟 tushare pro_api:按方法名返回 DataFrame。"""
    def __init__(self, report_rows, news_rows):
        self._report = report_rows
        self._news = news_rows

    def report_rc(self, **kw):
        import pandas as pd
        return pd.DataFrame(self._report)

    def news(self, **kw):
        import pandas as pd
        return pd.DataFrame(self._news)


def test_tushare_source_merges_reports_and_news():
    pro = FakePro(
        report_rows=[{"ts_code": "600519.SH", "report_title": "强烈推荐",
                      "rating": "买入", "tp_eps": None, "report_date": "20260601"}],
        news_rows=[{"datetime": "2026-06-01 09:00", "content": "公司新闻正文"}],
    )
    src = TushareResearchSource(pro, limiter=None)
    items = src.fetch("600519.SH", date(2026, 6, 2))
    assert any(i.rating == "买入" for i in items)
    assert any("公司新闻" in (i.text or "") for i in items)
    assert all(isinstance(i, ResearchItem) for i in items)


def test_tushare_source_empty_on_no_data():
    src = TushareResearchSource(FakePro([], []), limiter=None)
    assert src.fetch("000001.SZ", date(2026, 6, 2)) == []


def test_tushare_source_swallows_errors():
    class Boom:
        def report_rc(self, **kw): raise RuntimeError("api down")
        def news(self, **kw): raise RuntimeError("api down")
    src = TushareResearchSource(Boom(), limiter=None)
    assert src.fetch("000001.SZ", date(2026, 6, 2)) == []
