from app.decision.agents import Agent, AgentReport, ROLES


class FakeLLM:
    def __init__(self, reply): self.reply = reply; self.calls = []
    def complete(self, prompt, system=None):
        self.calls.append((prompt, system)); return self.reply


def test_agent_runs_and_parses_verdict():
    llm = FakeLLM('看多。 {"action": "BUY", "confidence": 0.7}')
    a = Agent(role="交易员", system="你是交易员", llm=llm)
    rep = a.run("某股简报")
    assert isinstance(rep, AgentReport)
    assert rep.role == "交易员"
    assert rep.verdict == {"action": "BUY", "confidence": 0.7}
    assert llm.calls[0][1] == "你是交易员"  # system passed through


def test_roles_catalog_has_expected_members():
    assert {"量价分析师", "基本面分析师", "多头研究员", "空头研究员",
            "交易员", "风控经理"} <= set(ROLES)
