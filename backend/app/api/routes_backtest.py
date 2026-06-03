from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.api.deps import get_session
from app.backtest.store import BacktestStore

router = APIRouter(prefix="/api", tags=["backtest"])


def _run_json(run):
    return {
        "id": run.id, "created_at": run.created_at.isoformat(),
        "signal": run.signal, "start": run.start.isoformat(),
        "end": run.end.isoformat(), "params": run.params_dict(),
        "strategy_metrics": run.strategy_metrics_dict(),
        "factor_report": run.factor_report_dict()}


@router.get("/backtest")
def latest_backtest(s: Session = Depends(get_session)):
    run = BacktestStore(s).latest()
    if run is None:
        raise HTTPException(status_code=404, detail="no backtest run")
    return _run_json(run)


@router.get("/backtest/runs")
def recent_backtests(n: int = 10, s: Session = Depends(get_session)):
    return [_run_json(r) for r in BacktestStore(s).list_recent(n)]
