from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.api.deps import get_session
from app.research.store import ResearchStore

router = APIRouter(prefix="/api", tags=["research"])


@router.get("/research/{code}")
def get_research(code: str, s: Session = Depends(get_session)):
    note = ResearchStore(s).latest(code)
    if note is None:
        raise HTTPException(status_code=404, detail="no research note")
    return {"code": note.code, "as_of": note.as_of.isoformat(),
            "sentiment": note.sentiment,
            "rating_consensus": note.rating_consensus,
            "summary": note.summary, "source": note.source}
