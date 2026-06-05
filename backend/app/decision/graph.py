from dataclasses import dataclass
from app.decision.agents import Agent, ROLES
from app.decision.brief import StockBrief


@dataclass
class Decision:
    action: str
    confidence: float
    shares: int
    reasoning: str


class DecisionGraph:
    def __init__(self, llm, rounds: int = 2):
        self.llm = llm
        self.rounds = rounds

    def _agent(self, role: str) -> Agent:
        return Agent(role, ROLES[role], self.llm)

    def run(self, brief: StockBrief) -> Decision:
        bp = brief.to_prompt()
        reports = []

        pv = self._agent("量价分析师").run(bp); reports.append(pv)
        fa = self._agent("基本面分析师").run(bp); reports.append(fa)
        cf = self._agent("财报分析师").run(bp); reports.append(cf)
        nr = self._agent("新闻研报分析师").run(bp); reports.append(nr)
        analyst_ctx = f"{pv.text}\n{fa.text}\n{cf.text}\n{nr.text}"

        bull_text, bear_text = "", ""
        for _ in range(self.rounds):
            bull = self._agent("多头研究员").run(
                f"{bp}\n分析师观点:\n{analyst_ctx}\n空头上轮:{bear_text}")
            bear = self._agent("空头研究员").run(
                f"{bp}\n分析师观点:\n{analyst_ctx}\n多头上轮:{bull.text}")
            reports += [bull, bear]
            bull_text, bear_text = bull.text, bear.text

        debate = f"多头:{bull_text}\n空头:{bear_text}"
        trader = self._agent("交易员").run(
            f"{bp}\n分析师:\n{analyst_ctx}\n辩论:\n{debate}")
        reports.append(trader)

        risk_ctx = f"交易员草案:{trader.text}"
        for role in ["激进风控", "保守风控", "中性风控"]:
            rep = self._agent(role).run(f"{bp}\n{risk_ctx}")
            reports.append(rep); risk_ctx += f"\n{role}:{rep.text}"
        rm = self._agent("风控经理").run(f"{bp}\n{risk_ctx}")
        reports.append(rm)

        v = rm.verdict
        reasoning = "\n\n".join(f"### {r.role}\n{r.text}" for r in reports)
        return Decision(
            action=str(v.get("action", "HOLD")),
            confidence=float(v.get("confidence", 0.0) or 0.0),
            shares=int(v.get("shares", 0) or 0),
            reasoning=reasoning,
        )
