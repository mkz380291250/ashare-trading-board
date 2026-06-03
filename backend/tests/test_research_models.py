from datetime import date
from sqlalchemy import select
from app.db.models import ResearchNote


def test_research_note_roundtrip(session):
    session.add(ResearchNote(code="600519.SH", as_of=date(2026, 6, 3),
                             sentiment=0.6, rating_consensus="买入x3 目标价1900",
                             summary="基本面稳健", source="tushare"))
    session.commit()
    row = session.scalar(select(ResearchNote).where(ResearchNote.code == "600519.SH"))
    assert row.sentiment == 0.6
    assert row.as_of == date(2026, 6, 3)
    assert row.summary == "基本面稳健"
