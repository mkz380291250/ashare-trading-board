import json
from dataclasses import dataclass


@dataclass(frozen=True)
class StockBrief:
    code: str
    recent_closes: list[float]
    factors: dict
    fundamentals: dict
    holding: dict | None
    research: dict | None = None
    financials: dict | None = None

    def to_prompt(self) -> str:
        last = self.recent_closes[-1] if self.recent_closes else None
        if self.holding:
            hold = f"持仓 {self.holding.get('shares')} 股,成本 {self.holding.get('cost')}"
        else:
            hold = "无持仓"
        if self.research:
            r = self.research
            research_line = (
                f"研报观点: 情绪分={r.get('sentiment')} "
                f"评级={r.get('rating_consensus','')} "
                f"摘要={r.get('summary','')}\n")
        else:
            research_line = "研报观点: 无研报数据\n"
        if self.financials:
            fin_line = f"财报数据: {json.dumps(self.financials, ensure_ascii=False)}\n"
        else:
            fin_line = "财报数据: 无\n"
        return (
            f"股票代码: {self.code}\n"
            f"最新收盘: {last}\n"
            f"近期收盘序列: {self.recent_closes}\n"
            f"量价因子: {json.dumps(self.factors, ensure_ascii=False)}\n"
            f"基本面: {json.dumps(self.fundamentals, ensure_ascii=False)}\n"
            f"{fin_line}"
            f"{research_line}"
            f"{hold}\n"
        )


def build_brief(code, recent_closes, factors, fundamentals, holding,
                research=None, financials=None) -> StockBrief:
    return StockBrief(code=code, recent_closes=list(recent_closes),
                      factors=dict(factors), fundamentals=dict(fundamentals),
                      holding=holding, research=research, financials=financials)
