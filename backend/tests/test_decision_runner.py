from datetime import date
from app.db.models import Decision
from app.decision.brief import build_brief
from app.decision.graph import DecisionGraph
from app.decision.runner import DecisionRunner


class ScriptedLLM:
    def complete(self, prompt, system=None):
        sys = system or ""
        if "风控经理" in sys:
            return '{"action": "BUY", "confidence": 0.8, "shares": 100}'
        if "交易员" in sys:
            return '{"action": "BUY", "confidence": 0.6, "shares": 100}'
        return '{"stance": "bull", "confidence": 0.7}'


def _briefs():
    return [build_brief("A.SH", [10.0, 11.0], {}, {}, None)]


def test_runner_persists_pending(session):
    runner = DecisionRunner(session, DecisionGraph(ScriptedLLM(), rounds=1))
    out = runner.run(date(2026, 5, 29), _briefs())
    assert len(out) == 1
    row = session.query(Decision).one()
    assert row.code == "A.SH" and row.action == "BUY" and row.status == "PENDING"
    assert "风控经理" in row.reasoning


def test_runner_idempotent_per_date_code(session):
    runner = DecisionRunner(session, DecisionGraph(ScriptedLLM(), rounds=1))
    runner.run(date(2026, 5, 29), _briefs())
    runner.run(date(2026, 5, 29), _briefs())
    assert session.query(Decision).count() == 1
