import json
from datetime import date
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.db.models import BacktestRun


class BacktestStore:
    def __init__(self, session: Session):
        self.s = session

    def save(self, *, signal: str, start: date, end: date, params: dict,
             strategy_metrics: dict, factor_report: dict,
             created_at: date) -> BacktestRun:
        run = BacktestRun(
            created_at=created_at, signal=signal, start=start, end=end,
            params=json.dumps(params, ensure_ascii=False),
            strategy_metrics=json.dumps(strategy_metrics, ensure_ascii=False),
            factor_report=json.dumps(factor_report, ensure_ascii=False))
        self.s.add(run)
        self.s.commit()
        return run

    def latest(self) -> BacktestRun | None:
        return self.s.scalar(
            select(BacktestRun).order_by(BacktestRun.id.desc()).limit(1))

    def list_recent(self, n: int = 10) -> list[BacktestRun]:
        return list(self.s.scalars(
            select(BacktestRun).order_by(BacktestRun.id.desc()).limit(n)))
