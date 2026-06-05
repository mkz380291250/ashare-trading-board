from datetime import date
from app.research.ondemand import research_note_for
from app.research.store import AnalyzedNote


class FakeNote:  # 模拟 ResearchNote 行
    def __init__(self, as_of, sentiment=0.3, rating="买入", summary="缓存摘要"):
        self.as_of = as_of
        self.sentiment = sentiment
        self.rating_consensus = rating
        self.summary = summary


class FakeStore:
    def __init__(self, cached=None):
        self._cached = cached
        self.upserts = []

    def latest(self, code):
        return self._cached

    def upsert(self, code, as_of, note, source):
        self.upserts.append((code, as_of, note, source))
        self._cached = FakeNote(as_of, note.sentiment, note.rating_consensus, note.summary)


class FakeItem:
    source = "tushare"


class FakeSource:
    def __init__(self, items=None, boom=False):
        self.items = items or []
        self.boom = boom
        self.calls = 0

    def fetch(self, code, as_of):
        self.calls += 1
        if self.boom:
            raise RuntimeError("network down")
        return self.items


class FakeAnalyzer:
    def analyze(self, code, items):
        return AnalyzedNote(sentiment=0.8, rating_consensus="强烈买入", summary="实时抓取摘要")


AS_OF = date(2026, 6, 5)


def test_uses_fresh_cache_without_fetching():
    src = FakeSource()
    r = research_note_for("X", AS_OF, src, FakeAnalyzer(), FakeStore(FakeNote(date(2026, 6, 4))))
    assert src.calls == 0
    assert r["summary"] == "缓存摘要"


def test_fetches_when_no_cache():
    src = FakeSource(items=[FakeItem()])
    store = FakeStore(cached=None)
    r = research_note_for("X", AS_OF, src, FakeAnalyzer(), store)
    assert src.calls == 1
    assert r["sentiment"] == 0.8 and r["summary"] == "实时抓取摘要"
    assert store.upserts and store.upserts[0][3] == "tushare"


def test_fetches_when_cache_stale():
    src = FakeSource(items=[FakeItem()])
    r = research_note_for("X", AS_OF, src, FakeAnalyzer(),
                          FakeStore(FakeNote(date(2026, 1, 1))), max_age_days=3)
    assert src.calls == 1 and r["summary"] == "实时抓取摘要"


def test_fetch_error_falls_back_to_old_cache():
    src = FakeSource(boom=True)
    r = research_note_for("X", AS_OF, src, FakeAnalyzer(),
                          FakeStore(FakeNote(date(2026, 1, 1))), max_age_days=3)
    assert r["summary"] == "缓存摘要"   # 抓取失败回退旧缓存


def test_fetch_error_no_cache_returns_none():
    src = FakeSource(boom=True)
    assert research_note_for("X", AS_OF, src, FakeAnalyzer(), FakeStore(None)) is None
