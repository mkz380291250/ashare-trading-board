from app.decision.brief import build_brief
from app.decision.graph import DecisionGraph, Decision


class ScriptedLLM:
    """Returns a canned reply keyed by which role's system prompt is seen."""
    def complete(self, prompt, system=None):
        sys = system or ""
        if "风控经理" in sys:   # check first: 风控经理 prompt also mentions 交易员
            return '最终批准 {"action": "BUY", "confidence": 0.8, "shares": 100}'
        if "交易员" in sys:
            return '草案买入 {"action": "BUY", "confidence": 0.6, "shares": 100}'
        return 'observation {"stance": "bull", "confidence": 0.7}'


def _brief():
    return build_brief("X", [10.0, 11.0], {"mom_5d": 0.1}, {"np_yoy": 20.0},
                       holding=None)


def test_graph_returns_final_risk_manager_decision():
    d = DecisionGraph(ScriptedLLM(), rounds=1).run(_brief())
    assert isinstance(d, Decision)
    assert d.action == "BUY" and d.confidence == 0.8 and d.shares == 100


def test_reasoning_includes_all_roles():
    d = DecisionGraph(ScriptedLLM(), rounds=1).run(_brief())
    for role in ["量价分析师", "基本面分析师", "多头研究员", "空头研究员",
                 "交易员", "风控经理"]:
        assert role in d.reasoning


def test_graph_defaults_hold_on_unparseable_final():
    class Mum:
        def complete(self, prompt, system=None): return "no verdict here"
    d = DecisionGraph(Mum(), rounds=1).run(_brief())
    assert d.action == "HOLD" and d.confidence == 0.0
