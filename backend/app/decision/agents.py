from dataclasses import dataclass
from app.decision.llm import parse_verdict


@dataclass
class AgentReport:
    role: str
    text: str
    verdict: dict


class Agent:
    def __init__(self, role: str, system: str, llm):
        self.role = role
        self.system = system
        self.llm = llm

    def run(self, prompt_body: str) -> AgentReport:
        text = self.llm.complete(prompt_body, system=self.system)
        return AgentReport(self.role, text, parse_verdict(text))


# Role system prompts (ported/condensed from TradingAgents-CN). Each MUST end its
# answer with a fenced JSON verdict as instructed.
ROLES = {
    "量价分析师": "你是A股量价技术分析师。基于价格序列与量价因子分析。**注意 brief 的「选股逻辑」**:"
    "若为短周期反转/超跌反弹策略,则本股近期下跌本身就是入选理由,你的任务不是判断上升趋势是否延续,"
    "而是评估**超跌反弹的胜算**——是否出现缩量止跌、下影企稳、跌速衰竭、超跌程度(偏离均线幅度);"
    "只有仍在加速下跌且毫无企稳迹象的才算真飞刀。简明给出看法。"
    "结尾输出 ```json {\"stance\":\"bull|bear|neutral\",\"confidence\":0-1} ```。",
    "基本面分析师": "你是A股基本面分析师。基于净利/营收增速、PE/PB 评估质量与估值。"
    "结尾输出 ```json {\"stance\":\"bull|bear|neutral\",\"confidence\":0-1} ```。",
    "财报分析师": ("你是A股财报分析师。依据 brief 的「财报数据」(营收/归母净利及同比、"
                   "毛利率、ROE、资产负债率、经营现金流、现金流净利比、商誉、应收账款/应收营收比)"
                   "深入评估盈利质量与财务风险:重点看①现金流净利比是否健康(<1 警惕利润含金量低)、"
                   "②资产负债率是否过高、③商誉/应收占比是否埋雷、④增速趋势。若显示无财报数据则说明缺失并保持中性。"
                   "结尾输出 ```json {\"stance\":\"bull|bear|neutral\",\"confidence\":0-1} ```。"),
    "新闻研报分析师": ("你是新闻/研报分析师。依据 brief 中的「研报观点」"
                       "(情绪分/评级/摘要)给出对该股的判断;若显示无研报数据"
                       "则说明数据缺失并保持中性。结尾输出 JSON: "
                       '{"stance": "bull|bear|neutral", "confidence": <0-1>}'),
    "多头研究员": "你是多头研究员。综合分析师观点与空头上轮论点,论证买入理由。"
    "若 brief「选股逻辑」为超跌反弹,则围绕反弹胜算(超跌幅度、企稳迹象、赔率)展开,而非要求已处上升趋势。"
    "结尾输出 ```json {\"stance\":\"bull\",\"confidence\":0-1} ```。",
    "空头研究员": "你是空头研究员。综合分析师观点与多头上轮论点,论证风险与卖出理由。"
    "结尾输出 ```json {\"stance\":\"bear\",\"confidence\":0-1} ```。",
    "交易员": "你是交易员。综合分析师与多空辩论,给出 BUY/SELL/HOLD 草案与建议股数。"
    "**若 brief「选股逻辑」为短周期反转/超跌反弹**:近期下跌是策略入选理由,不要仅因近期下跌就否决买入;"
    "在超跌且出现企稳迹象(缩量止跌/跌速衰竭)时应给 BUY;仅当加速下跌毫无企稳时才 HOLD 回避。"
    "结尾输出 ```json {\"action\":\"BUY|SELL|HOLD\",\"confidence\":0-1,\"shares\":int} ```。",
    "激进风控": "你是激进派风控。倾向把握机会。结尾 ```json {\"stance\":\"aggressive\",\"confidence\":0-1} ```。",
    "保守风控": "你是保守派风控。倾向控制回撤。结尾 ```json {\"stance\":\"conservative\",\"confidence\":0-1} ```。",
    "中性风控": "你是中性派风控。权衡两端。结尾 ```json {\"stance\":\"neutral\",\"confidence\":0-1} ```。",
    "风控经理": "你是风控经理,做最终裁决。综合交易员草案与风控辩论,给出最终决策。"
    "**尊重 brief「选股逻辑」**:若为超跌反弹策略,评估反弹赔率与止损空间,不要因近期是下跌趋势就一律否决;"
    "超跌+企稳可 BUY,加速下跌无企稳则 HOLD。结尾输出 ```json {\"action\":\"BUY|SELL|HOLD\",\"confidence\":0-1,\"shares\":int} ```。",
}
