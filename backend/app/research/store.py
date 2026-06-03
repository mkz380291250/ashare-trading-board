from dataclasses import dataclass
from datetime import date
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.db.models import ResearchNote


@dataclass(frozen=True)
class AnalyzedNote:
    sentiment: float
    rating_consensus: str
    summary: str


class ResearchStore:
    def __init__(self, session: Session):
        self.s = session

    def upsert(self, code: str, as_of: date, note: AnalyzedNote, source: str) -> None:
        row = self.s.get(ResearchNote, (code, as_of))
        if row is None:
            row = ResearchNote(code=code, as_of=as_of)
            self.s.add(row)
        row.sentiment = note.sentiment
        row.rating_consensus = note.rating_consensus
        row.summary = note.summary
        row.source = source
        self.s.commit()

    def latest(self, code: str) -> ResearchNote | None:
        return self.s.scalar(
            select(ResearchNote).where(ResearchNote.code == code)
            .order_by(ResearchNote.as_of.desc()).limit(1))

    def list_latest(self, limit: int = 50) -> list:
        """每只股取最新一条笔记,按 as_of 倒序,最多 limit 条。"""
        rows = self.s.scalars(
            select(ResearchNote).order_by(ResearchNote.as_of.desc())).all()
        seen, out = set(), []
        for r in rows:
            if r.code in seen:
                continue
            seen.add(r.code)
            out.append(r)
            if len(out) >= limit:
                break
        return out
