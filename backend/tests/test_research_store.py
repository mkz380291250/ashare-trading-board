from datetime import date
from app.research.store import ResearchStore, AnalyzedNote


def test_upsert_and_latest(session):
    st = ResearchStore(session)
    st.upsert("600519.SH", date(2026, 6, 1), AnalyzedNote(0.5, "增持", "稳"), "tushare")
    note = st.latest("600519.SH")
    assert note.sentiment == 0.5 and note.summary == "稳"


def test_upsert_is_idempotent_same_key(session):
    st = ResearchStore(session)
    st.upsert("600519.SH", date(2026, 6, 1), AnalyzedNote(0.5, "a", "s1"), "x")
    st.upsert("600519.SH", date(2026, 6, 1), AnalyzedNote(0.9, "b", "s2"), "y")
    note = st.latest("600519.SH")
    assert note.sentiment == 0.9 and note.summary == "s2"  # 覆盖


def test_latest_returns_most_recent_date(session):
    st = ResearchStore(session)
    st.upsert("000001.SZ", date(2026, 6, 1), AnalyzedNote(0.1, "", "old"), "x")
    st.upsert("000001.SZ", date(2026, 6, 3), AnalyzedNote(0.2, "", "new"), "x")
    assert st.latest("000001.SZ").summary == "new"


def test_latest_none_when_absent(session):
    assert ResearchStore(session).latest("000001.SZ") is None
