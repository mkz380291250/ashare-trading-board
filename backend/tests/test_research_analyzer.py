from app.research.analyzer import ResearchAnalyzer
from app.research.store import AnalyzedNote
from app.research.sources import ResearchItem


class FakeLLM:
    def __init__(self, reply): self.reply = reply
    def complete(self, prompt, system=None): return self.reply


def _items():
    return [ResearchItem("研报", "看多 目标价 1900", "20260601", rating="买入")]


def test_analyze_parses_structured_json():
    llm = FakeLLM('结论 {"sentiment": 0.7, "rating_consensus": "买入", '
                  '"summary": "基本面强"}')
    note = ResearchAnalyzer(llm).analyze("600519.SH", _items())
    assert isinstance(note, AnalyzedNote)
    assert note.sentiment == 0.7 and note.summary == "基本面强"


def test_analyze_empty_items_is_neutral_without_llm():
    class Boom:
        def complete(self, *a, **k): raise AssertionError("must not call LLM")
    note = ResearchAnalyzer(Boom()).analyze("X", [])
    assert note.sentiment == 0.0 and "缺失" in note.summary


def test_analyze_unparseable_falls_back_neutral():
    note = ResearchAnalyzer(FakeLLM("无 json 输出")).analyze("X", _items())
    assert note.sentiment == 0.0
    assert note.summary  # 非空(截断原文/兜底文案)


def test_analyze_clamps_sentiment_range():
    note = ResearchAnalyzer(FakeLLM('{"sentiment": 5, "rating_consensus": "", '
                                    '"summary": "s"}')).analyze("X", _items())
    assert note.sentiment == 1.0  # clamp 到 [-1,1]
