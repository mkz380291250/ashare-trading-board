# backend/tests/test_policy_guardrails.py
import json
from datetime import date
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from app.db.database import Base
import app.db.models  # noqa
from app.db.models import PolicyAction
from app.policy.guardrails import record_action


def _sess():
    e = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(e)
    return sessionmaker(bind=e, future=True)()


def test_record_action_persists_audit():
    s = _sess()
    pa = record_action(s, "RISK_OFF", date(2026, 6, 28),
                       {"drawdown": -0.22}, "回撤 -22% 破 20%,当日停买")
    assert pa.id is not None
    row = s.scalar(select(PolicyAction))
    assert row.kind == "RISK_OFF" and row.status == "AUTO"
    assert json.loads(row.trigger)["drawdown"] == -0.22
    assert row.weixin_sent is False


# run_remine 用 monkeypatch 截 subprocess,不真起进程
def test_run_remine_invokes_mining_then_freeze(monkeypatch):
    from app.policy import actions
    calls = []

    class _R:
        returncode = 0

    def fake_run(cmd, **kw):
        calls.append(cmd)
        return _R()

    monkeypatch.setattr(actions.subprocess, "run", fake_run)
    rc = actions.run_remine()
    assert rc == 0
    assert len(calls) == 2                       # mining 然后 freeze
    assert "run_factor_mining.py" in " ".join(map(str, calls[0]))
    assert "freeze_factors.py" in " ".join(map(str, calls[1]))


def test_run_remine_stops_on_mining_failure(monkeypatch):
    from app.policy import actions
    calls = []

    class _R:
        def __init__(self, rc): self.returncode = rc

    def fake_run(cmd, **kw):
        calls.append(cmd)
        return _R(1)                             # mining 失败

    monkeypatch.setattr(actions.subprocess, "run", fake_run)
    rc = actions.run_remine()
    assert rc == 1
    assert len(calls) == 1                        # freeze 不再执行
