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


def test_list_latest_one_per_code_newest(session):
    st = ResearchStore(session)
    st.upsert("600519.SH", date(2026, 6, 1), AnalyzedNote(0.1, "", "old"), "s")
    st.upsert("600519.SH", date(2026, 6, 3), AnalyzedNote(0.5, "", "new"), "s")
    st.upsert("000001.SZ", date(2026, 6, 2), AnalyzedNote(0.2, "", "x"), "s")
    rows = st.list_latest(10)
    assert [r.code for r in rows] == ["600519.SH", "000001.SZ"]
    assert rows[0].summary == "new"


def test_research_as_dict_fresh_and_stale():
    # 研报要新鲜:7天内的转 dict 喂辩论,过期的宁可不给(免得旧观点误导)
    from datetime import date
    from app.db.models import ResearchNote
    from app.research.store import research_as_dict

    fresh = ResearchNote(code="X.SZ", as_of=date(2026, 7, 1), sentiment=0.6,
                         rating_consensus="买入", summary="ok", source="t")
    stale = ResearchNote(code="X.SZ", as_of=date(2026, 6, 20), sentiment=0.6,
                         rating_consensus="买入", summary="old", source="t")
    d = research_as_dict(fresh, date(2026, 7, 3))
    assert d == {"sentiment": 0.6, "rating_consensus": "买入", "summary": "ok"}
    assert research_as_dict(stale, date(2026, 7, 3)) is None
    assert research_as_dict(None, date(2026, 7, 3)) is None
