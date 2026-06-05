from sqlalchemy import select
from sqlalchemy.orm import Session
from app.db.models import StockName


class NameLookup:
    def __init__(self, session: Session):
        self.s = session

    def map(self, codes) -> dict[str, str]:
        codes = list({c for c in codes})
        if not codes:
            return {}
        rows = self.s.scalars(select(StockName).where(StockName.code.in_(codes))).all()
        return {r.code: r.name for r in rows}

    def get(self, code: str) -> str:
        r = self.s.get(StockName, code)
        return r.name if r else ""
