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


def test_runner_isolates_per_brief_failures(session, capsys):
    # 一只票的辩论崩溃(如 LLM 调用失败)不应带崩整晚:跳过该票,其余照常决策
    class FlakyGraph:
        def run(self, brief):
            if brief.code == "BAD.SZ":
                raise FileNotFoundError("/usr/local/bin/claude")
            from app.decision.graph import Decision as D
            return D(action="HOLD", confidence=0.5, shares=0, reasoning="ok")

    briefs = [build_brief(c, [1.0], {}, {}, None)
              for c in ("GOOD1.SZ", "BAD.SZ", "GOOD2.SZ")]
    out = DecisionRunner(session, FlakyGraph()).run(date(2026, 7, 3), briefs)
    codes = {d.code for d in out}
    assert codes == {"GOOD1.SZ", "GOOD2.SZ"}   # BAD 跳过,其余正常落库
    assert "DEBATE_SKIP BAD.SZ" in capsys.readouterr().out


def test_runner_aborts_whole_run_on_usage_limit(session):
    # 账号限额是全局状态:后续每只都会同样失败,继续跑只会写垃圾决策
    # (2026-07-06 事故:限额提示被当发言,8只全 HOLD/0.0 落库)——应整场中止且不落库
    import pytest
    from app.decision.llm import UsageLimitError

    class LimitedGraph:
        def run(self, brief):
            if brief.code == "B.SZ":
                raise UsageLimitError("You've hit your session limit")
            from app.decision.graph import Decision as D
            return D(action="HOLD", confidence=0.5, shares=0, reasoning="ok")

    briefs = [build_brief(c, [1.0], {}, {}, None) for c in ("A.SZ", "B.SZ", "C.SZ")]
    with pytest.raises(UsageLimitError):
        DecisionRunner(session, LimitedGraph()).run(date(2026, 7, 6), briefs)
    session.rollback()
    assert session.query(Decision).count() == 0   # A.SZ 也不该提交
