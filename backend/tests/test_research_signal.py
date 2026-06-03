from datetime import date
from app.research.store import ResearchStore, AnalyzedNote
from app.research.signal import ResearchSignalProvider
from app.discovery.snapshot import StockData


def _snap(*codes):
    return {c: StockData(c, [10.0], [10.0], [1.0], None) for c in codes}


def test_provider_returns_sentiment_only_for_covered(session):
    st = ResearchStore(session)
    st.upsert("600519.SH", date(2026, 6, 3), AnalyzedNote(0.8, "", "x"), "s")
    out = ResearchSignalProvider(st).compute(_snap("600519.SH", "000001.SZ"))
    assert out["research_sent"] == {"600519.SH": 0.8}  # 000001 无笔记不出现


def test_provider_empty_when_no_notes(session):
    out = ResearchSignalProvider(ResearchStore(session)).compute(_snap("000001.SZ"))
    assert out == {"research_sent": {}}
