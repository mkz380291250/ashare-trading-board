from datetime import date
from app.research.store import ResearchStore, AnalyzedNote
from app.research.runner import ResearchRunner


class FakeSource:
    def __init__(self): self.calls = []
    def fetch(self, code, as_of):
        self.calls.append(code)
        return [object()]  # 非空即可,analyzer 被 fake


class FakeAnalyzer:
    def analyze(self, code, items):
        return AnalyzedNote(0.3, "增持", f"note-{code}")


def test_runner_persists_each_code(session):
    st = ResearchStore(session)
    src = FakeSource()
    ResearchRunner(src, FakeAnalyzer(), st).run({"600519.SH", "000001.SZ"},
                                                date(2026, 6, 3))
    assert sorted(src.calls) == ["000001.SZ", "600519.SH"]
    assert st.latest("600519.SH").summary == "note-600519.SH"


def test_runner_idempotent_rerun_overwrites(session):
    st = ResearchStore(session)
    r = ResearchRunner(FakeSource(), FakeAnalyzer(), st)
    r.run({"600519.SH"}, date(2026, 6, 3))
    r.run({"600519.SH"}, date(2026, 6, 3))  # 重跑不报错
    assert st.latest("600519.SH").sentiment == 0.3


def test_runner_continues_on_single_failure(session):
    class FlakyAnalyzer:
        def analyze(self, code, items):
            if code == "BAD":
                raise RuntimeError("llm down")
            return AnalyzedNote(0.1, "", "ok")
    st = ResearchStore(session)
    ResearchRunner(FakeSource(), FlakyAnalyzer(), st).run(
        {"BAD", "600519.SH"}, date(2026, 6, 3))
    assert st.latest("600519.SH") is not None  # 好的那只仍落库
    assert st.latest("BAD") is None
