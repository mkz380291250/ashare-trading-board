import re
import sys
import subprocess
from datetime import date as date_t
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from app.api.deps import get_session
from app.data.names import NameLookup
from app.db.models import Decision, DecisionJob
from app.decision.reasoning_parse import parse_reasoning
from app.screener.tracklist_parser import normalize_code
from app.trading.broker import PaperBroker, InsufficientFunds, InsufficientShares

router = APIRouter(prefix="/api", tags=["decisions"])


class ApproveBody(BaseModel):
    price: float = 0.0
    account_id: int = 1


class RunBody(BaseModel):
    code: str


def _spawn_decision_worker(job_id: int, code: str) -> None:
    root = Path(__file__).resolve().parents[2]   # backend/
    script = root / "scripts" / "run_one_decision.py"
    subprocess.Popen(["setsid", sys.executable, str(script), "--code", code, "--job", str(job_id)],
                     cwd=str(root), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     start_new_session=True)


@router.post("/decisions/run")
def run_decision(body: RunBody, s: Session = Depends(get_session)):
    code = normalize_code(body.code)
    job = DecisionJob(code=code, status="PENDING", created_at=date_t.today())
    s.add(job); s.commit(); s.refresh(job)
    _spawn_decision_worker(job.id, code)
    return {"id": job.id, "code": job.code, "status": job.status}


@router.get("/decisions/jobs")
def list_jobs(s: Session = Depends(get_session)):
    rows = s.scalars(select(DecisionJob).order_by(DecisionJob.id.desc()).limit(20)).all()
    return [{"id": j.id, "code": j.code, "status": j.status,
             "decision_id": j.decision_id, "error": j.error} for j in rows]


@router.get("/decisions")
def list_decisions(date: date_t | None = None, s: Session = Depends(get_session)):
    target = date or s.scalar(select(func.max(Decision.as_of)))
    if target is None:
        return []
    rows = s.scalars(select(Decision).where(Decision.as_of == target)
                     .order_by(Decision.code)).all()
    names = NameLookup(s).map([r.code for r in rows])
    return [{"id": r.id, "as_of": r.as_of.isoformat(), "code": r.code,
             "name": names.get(r.code, ""),
             "action": r.action, "confidence": r.confidence, "shares": r.shares,
             "status": r.status, "reasoning": r.reasoning} for r in rows]


@router.get("/decisions/{decision_id}")
def get_decision(decision_id: int, s: Session = Depends(get_session)):
    d = s.get(Decision, decision_id)
    if d is None:
        raise HTTPException(404, "decision not found")
    roles = parse_reasoning(d.reasoning)
    verdict_text = next((r.text for r in roles if r.stage == "verdict"), "")
    summary = re.split(r"[。\n]", verdict_text.strip(), maxsplit=1)[0] if verdict_text else ""
    return {
        "id": d.id, "code": d.code, "name": NameLookup(s).get(d.code),
        "action": d.action, "confidence": d.confidence, "shares": d.shares,
        "status": d.status, "summary": summary,
        "roles": [{"role": r.role, "stage": r.stage, "stance": r.stance,
                   "action": r.action, "confidence": r.confidence, "text": r.text}
                  for r in roles],
    }


@router.post("/decisions/{decision_id}/approve")
def approve(decision_id: int, body: ApproveBody, s: Session = Depends(get_session)):
    d = s.get(Decision, decision_id)
    if d is None:
        raise HTTPException(404, "decision not found")
    if d.status != "PENDING":
        return {"status": d.status}
    if d.action in ("BUY", "SELL") and d.shares > 0:
        broker = PaperBroker(s)
        try:
            if d.action == "BUY":
                broker.buy(body.account_id, d.code, body.price, d.shares, d.as_of)
            else:
                broker.sell(body.account_id, d.code, body.price, d.shares, d.as_of)
        except (InsufficientFunds, InsufficientShares) as e:
            raise HTTPException(400, str(e))
    d.status = "APPROVED"
    s.commit()
    return {"status": "APPROVED"}


@router.post("/decisions/{decision_id}/reject")
def reject(decision_id: int, s: Session = Depends(get_session)):
    d = s.get(Decision, decision_id)
    if d is None:
        raise HTTPException(404, "decision not found")
    d.status = "REJECTED"; s.commit()
    return {"status": "REJECTED"}
