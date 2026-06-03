from app.decision.llm import parse_verdict
from app.research.store import AnalyzedNote
from app.research.sources import ResearchItem

_SYS = ("你是A股研报/新闻分析师。基于给定的研报与新闻条目,判断该股的"
        "市场情绪与机构观点。最后必须输出一行 JSON: "
        '{"sentiment": <-1到1的浮点,负面到正面>, '
        '"rating_consensus": "<券商评级/目标价聚合,一句话>", '
        '"summary": "<中文摘要,2-4句>"}')


def _clamp(x: float) -> float:
    try:
        v = float(x)
    except Exception:
        return 0.0
    return max(-1.0, min(1.0, v))


class ResearchAnalyzer:
    def __init__(self, llm):
        self.llm = llm

    def analyze(self, code: str, items: list[ResearchItem]) -> AnalyzedNote:
        if not items:
            return AnalyzedNote(0.0, "", "数据缺失,保持中性")
        body = "\n".join(
            f"- [{it.source}] {it.title} {it.text} "
            f"评级={it.rating or ''} 目标价={it.target_price or ''}"
            for it in items)[:20000]
        prompt = f"股票代码: {code}\n研报与新闻:\n{body}"
        text = self.llm.complete(prompt, system=_SYS)
        v = parse_verdict(text)
        if not v:
            return AnalyzedNote(0.0, "", (text or "无法解析")[:500])
        return AnalyzedNote(
            sentiment=_clamp(v.get("sentiment", 0.0)),
            rating_consensus=str(v.get("rating_consensus", "")),
            summary=str(v.get("summary", "")) or (text or "")[:500])
