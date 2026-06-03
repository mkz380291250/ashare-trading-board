# 切片4 研报财报分析 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把券商研报/新闻经 LLM 消化成结构化「研报笔记」缓存入库,作为发现引擎的可插拔质化信号 + 决策引擎「新闻研报分析师」的数据源。

**Architecture:** 新模块 `app/research/`(sources → analyzer → store → runner)。研报范围 = 持仓∪最新发现Top8∪选股池。发现引擎 scorer 由「因子取交集」改为「并集 + 缺失中性 0.5 填充」,研报成为稀疏因子。决策 brief 加研报段。LLM 复用 decision 的 `LLMClient` 抽象,`research_llm` 默认 `local`(Claude),可切 `deepseek`。

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy 2.x (Mapped/mapped_column), pytest, tushare, requests, pandas。所有测试用注入式 fake(假 LLM/假 fetch),不打真实网络;末尾一个冒烟任务跑真实接口。

工作目录:`backend/`。运行测试统一 `cd backend && .venv/bin/python -m pytest`。分支:`slice-4`(已创建,基于 main)。

---

### Task 0: config 增加 research 配置项

**Files:**
- Modify: `backend/app/config.py`
- Test: `backend/tests/test_config.py`

- [ ] **Step 1: 写失败测试**

追加到 `backend/tests/test_config.py`:

```python
def test_research_config_defaults():
    from app.config import Settings
    s = Settings()
    assert s.research_llm == "local"
    assert s.research_max_per_min == 50
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_config.py::test_research_config_defaults -v`
Expected: FAIL（`AttributeError` / 无 `research_llm`）

- [ ] **Step 3: 实现**

在 `backend/app/config.py` 的 `Settings` 类里,`debate_rounds` 行之后加:

```python
    research_llm: str = "local"            # local | deepseek
    research_max_per_min: int = 50         # tushare 研报接口限流(保守)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_config.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add app/config.py tests/test_config.py
git commit -m "feat(config): research_llm + research_max_per_min settings"
```

---

### Task 1: ResearchNote ORM 模型 + research_notes 表

**Files:**
- Modify: `backend/app/db/models.py`（在 WatchPoolEntry 之后追加）
- Test: `backend/tests/test_research_models.py`（新建）

- [ ] **Step 1: 写失败测试**

新建 `backend/tests/test_research_models.py`:

用 conftest 的 `session` fixture（已 create_all + 注册模型）:

```python
from datetime import date
from sqlalchemy import select
from app.db.models import ResearchNote


def test_research_note_roundtrip(session):
    session.add(ResearchNote(code="600519.SH", as_of=date(2026, 6, 3),
                             sentiment=0.6, rating_consensus="买入x3 目标价1900",
                             summary="基本面稳健", source="tushare"))
    session.commit()
    row = session.scalar(select(ResearchNote).where(ResearchNote.code == "600519.SH"))
    assert row.sentiment == 0.6
    assert row.as_of == date(2026, 6, 3)
    assert row.summary == "基本面稳健"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_research_models.py -v`
Expected: FAIL（`ImportError: cannot import name 'ResearchNote'`）

- [ ] **Step 3: 实现**

在 `backend/app/db/models.py` 末尾追加（`WatchPoolEntry` 之后）:

```python
class ResearchNote(Base):
    __tablename__ = "research_notes"
    code: Mapped[str] = mapped_column(String(16), primary_key=True)
    as_of: Mapped[date] = mapped_column(Date, primary_key=True)
    sentiment: Mapped[float] = mapped_column(Float, default=0.0)  # -1..1
    rating_consensus: Mapped[str] = mapped_column(String, default="")
    summary: Mapped[str] = mapped_column(String, default="")
    source: Mapped[str] = mapped_column(String(32), default="")


Index("ix_research_notes_as_of", ResearchNote.as_of)
```

（`Index`、`String`、`Float`、`Date`、`Mapped`、`mapped_column` 在文件顶部已 import。）

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_research_models.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add app/db/models.py tests/test_research_models.py
git commit -m "feat(research): ResearchNote ORM model + research_notes table"
```

---

### Task 2: AnalyzedNote 数据类 + ResearchStore

**Files:**
- Create: `backend/app/research/__init__.py`（空）
- Create: `backend/app/research/store.py`
- Test: `backend/tests/test_research_store.py`（新建）

说明:`AnalyzedNote` 是 analyzer 的纯分析输出(无 code/as_of),store 负责拼主键落库。

- [ ] **Step 1: 写失败测试**

新建 `backend/tests/test_research_store.py`:

用 conftest 的 `session` fixture:

```python
from datetime import date
from app.research.store import ResearchStore, AnalyzedNote


def test_upsert_and_latest(session):
    st = ResearchStore(session)
    st.upsert("600519.SH", date(2026, 6, 1), AnalyzedNote(0.5, "增持", "稳"), "tushare")
    note = st.latest("600519.SH")
    assert note.sentiment == 0.5 and note.summary == "稳"


def test_upsert_is_idempotent_same_key(session):
    st = ResearchStore(session)
    st.upsert("600519.SH", date(2026, 6, 1), AnalyzedNote(0.5, "a", "s1"), "x")
    st.upsert("600519.SH", date(2026, 6, 1), AnalyzedNote(0.9, "b", "s2"), "y")
    note = st.latest("600519.SH")
    assert note.sentiment == 0.9 and note.summary == "s2"  # 覆盖


def test_latest_returns_most_recent_date(session):
    st = ResearchStore(session)
    st.upsert("000001.SZ", date(2026, 6, 1), AnalyzedNote(0.1, "", "old"), "x")
    st.upsert("000001.SZ", date(2026, 6, 3), AnalyzedNote(0.2, "", "new"), "x")
    assert st.latest("000001.SZ").summary == "new"


def test_latest_map_and_missing(session):
    st = ResearchStore(session)
    st.upsert("000001.SZ", date(2026, 6, 3), AnalyzedNote(0.2, "", "x"), "s")
    m = st.latest_map(["000001.SZ", "999999.SZ"])
    assert "000001.SZ" in m and "999999.SZ" not in m


def test_latest_none_when_absent(session):
    assert ResearchStore(session).latest("000001.SZ") is None
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_research_store.py -v`
Expected: FAIL（`ModuleNotFoundError: app.research.store`）

- [ ] **Step 3: 实现**

新建空文件 `backend/app/research/__init__.py`。

新建 `backend/app/research/store.py`:

```python
from dataclasses import dataclass
from datetime import date
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.db.models import ResearchNote


@dataclass(frozen=True)
class AnalyzedNote:
    sentiment: float
    rating_consensus: str
    summary: str


class ResearchStore:
    def __init__(self, session: Session):
        self.s = session

    def upsert(self, code: str, as_of: date, note: AnalyzedNote, source: str) -> None:
        row = self.s.get(ResearchNote, (code, as_of))
        if row is None:
            row = ResearchNote(code=code, as_of=as_of)
            self.s.add(row)
        row.sentiment = note.sentiment
        row.rating_consensus = note.rating_consensus
        row.summary = note.summary
        row.source = source
        self.s.commit()

    def latest(self, code: str) -> ResearchNote | None:
        return self.s.scalar(
            select(ResearchNote).where(ResearchNote.code == code)
            .order_by(ResearchNote.as_of.desc()).limit(1))

    def latest_map(self, codes: list[str]) -> dict[str, ResearchNote]:
        out: dict[str, ResearchNote] = {}
        for c in codes:
            note = self.latest(c)
            if note is not None:
                out[c] = note
        return out
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_research_store.py -v`
Expected: PASS（5 个）

- [ ] **Step 5: 提交**

```bash
git add app/research/__init__.py app/research/store.py tests/test_research_store.py
git commit -m "feat(research): AnalyzedNote + ResearchStore (idempotent upsert, latest)"
```

---

### Task 3: ResearchItem + ResearchSource 接口 + TushareResearchSource

**Files:**
- Create: `backend/app/research/sources.py`
- Test: `backend/tests/test_research_sources.py`（新建）

说明:`pro` 句柄注入(测试传 fake,生产传 `tushare.pro_api`)。tushare `report_rc` 返回券商评级/目标价,`news` 返回新闻。

- [ ] **Step 1: 写失败测试**

新建 `backend/tests/test_research_sources.py`:

```python
from datetime import date
from app.research.sources import ResearchItem, TushareResearchSource


class FakePro:
    """模拟 tushare pro_api:按方法名返回 DataFrame-like。"""
    def __init__(self, report_rows, news_rows):
        self._report = report_rows
        self._news = news_rows

    def report_rc(self, **kw):
        import pandas as pd
        return pd.DataFrame(self._report)

    def news(self, **kw):
        import pandas as pd
        return pd.DataFrame(self._news)


def test_tushare_source_merges_reports_and_news():
    pro = FakePro(
        report_rows=[{"ts_code": "600519.SH", "report_title": "强烈推荐",
                      "rating": "买入", "tp_eps": None, "report_date": "20260601"}],
        news_rows=[{"datetime": "2026-06-01 09:00", "content": "公司新闻正文"}],
    )
    src = TushareResearchSource(pro, limiter=None)
    items = src.fetch("600519.SH", date(2026, 6, 2))
    assert any(i.rating == "买入" for i in items)
    assert any("公司新闻" in (i.text or "") for i in items)
    assert all(isinstance(i, ResearchItem) for i in items)


def test_tushare_source_empty_on_no_data():
    src = TushareResearchSource(FakePro([], []), limiter=None)
    assert src.fetch("000001.SZ", date(2026, 6, 2)) == []


def test_tushare_source_swallows_errors():
    class Boom:
        def report_rc(self, **kw): raise RuntimeError("api down")
        def news(self, **kw): raise RuntimeError("api down")
    src = TushareResearchSource(Boom(), limiter=None)
    assert src.fetch("000001.SZ", date(2026, 6, 2)) == []
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_research_sources.py -v`
Expected: FAIL（`ModuleNotFoundError: app.research.sources`）

- [ ] **Step 3: 实现**

新建 `backend/app/research/sources.py`:

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class ResearchItem:
    title: str
    text: str
    date: str
    rating: str | None = None
    target_price: float | None = None
    source: str = ""


class ResearchSource(ABC):
    @abstractmethod
    def fetch(self, code: str, as_of: date) -> list[ResearchItem]:
        ...


def _rows(df):
    """tushare 返回 DataFrame;统一成 list[dict]。None/空 → []。"""
    if df is None:
        return []
    try:
        if getattr(df, "empty", False):
            return []
        return df.to_dict("records")
    except Exception:
        return []


class TushareResearchSource(ResearchSource):
    def __init__(self, pro, limiter=None):
        self.pro = pro
        self.limiter = limiter

    def fetch(self, code: str, as_of: date) -> list[ResearchItem]:
        items: list[ResearchItem] = []
        if self.limiter:
            self.limiter.acquire()
        try:
            for r in _rows(self.pro.report_rc(ts_code=code)):
                items.append(ResearchItem(
                    title=str(r.get("report_title") or ""),
                    text=str(r.get("report_title") or ""),
                    date=str(r.get("report_date") or ""),
                    rating=r.get("rating"),
                    target_price=r.get("tp_eps"),
                    source="tushare:report_rc"))
        except Exception:
            pass
        if self.limiter:
            self.limiter.acquire()
        try:
            for r in _rows(self.pro.news(src="sina")):
                items.append(ResearchItem(
                    title="", text=str(r.get("content") or ""),
                    date=str(r.get("datetime") or ""),
                    source="tushare:news"))
        except Exception:
            pass
        return items
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_research_sources.py -v`
Expected: PASS（3 个）

- [ ] **Step 5: 提交**

```bash
git add app/research/sources.py tests/test_research_sources.py
git commit -m "feat(research): ResearchItem + TushareResearchSource (report_rc + news)"
```

---

### Task 4: EastMoneyNewsSource + CompositeSource

**Files:**
- Modify: `backend/app/research/sources.py`
- Test: `backend/tests/test_research_sources.py`（追加）

说明:EastMoney 用注入式 `fetch_fn`(测试传 fake,生产传基于 requests 的真实抓取),失败返 []。CompositeSource 合并多源、按 title+text 去重。

- [ ] **Step 1: 写失败测试**

追加到 `backend/tests/test_research_sources.py`:

```python
from app.research.sources import EastMoneyNewsSource, CompositeSource


def test_eastmoney_source_maps_items():
    def fake_fetch(code):
        return [{"title": "利好公告", "content": "正文", "date": "2026-06-01"}]
    src = EastMoneyNewsSource(fetch_fn=fake_fetch)
    items = src.fetch("600519.SH", date(2026, 6, 2))
    assert items[0].title == "利好公告" and items[0].source == "eastmoney"


def test_eastmoney_source_empty_on_error():
    def boom(code): raise RuntimeError("blocked")
    assert EastMoneyNewsSource(fetch_fn=boom).fetch("x", date(2026, 6, 2)) == []


def test_composite_merges_and_dedups():
    class S1(ResearchSource):
        def fetch(self, code, as_of):
            return [ResearchItem("A", "ta", "d", source="s1")]
    class S2(ResearchSource):
        def fetch(self, code, as_of):
            return [ResearchItem("A", "ta", "d", source="s2"),  # dup of S1
                    ResearchItem("B", "tb", "d", source="s2")]
    items = CompositeSource([S1(), S2()]).fetch("x", date(2026, 6, 2))
    titles = sorted(i.title for i in items)
    assert titles == ["A", "B"]  # A 去重一次
```

（`from app.research.sources import ResearchItem, ResearchSource` 已在文件顶部 import；若未,补上。）

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_research_sources.py -v`
Expected: FAIL（`ImportError: EastMoneyNewsSource`）

- [ ] **Step 3: 实现**

在 `backend/app/research/sources.py` 末尾追加:

```python
def _em_default_fetch(code: str) -> list[dict]:
    """生产用:requests 抓 eastmoney 个股资讯。失败抛异常由调用方吞。
    (端点细节留待联调;沿用 screener 的 requests+重试模式。)"""
    raise NotImplementedError("wire real eastmoney endpoint during smoke task")


class EastMoneyNewsSource(ResearchSource):
    def __init__(self, fetch_fn=_em_default_fetch):
        self.fetch_fn = fetch_fn

    def fetch(self, code: str, as_of: date) -> list[ResearchItem]:
        try:
            rows = self.fetch_fn(code) or []
        except Exception:
            return []
        return [ResearchItem(
            title=str(r.get("title") or ""), text=str(r.get("content") or ""),
            date=str(r.get("date") or ""), source="eastmoney") for r in rows]


class CompositeSource(ResearchSource):
    def __init__(self, sources: list[ResearchSource]):
        self.sources = sources

    def fetch(self, code: str, as_of: date) -> list[ResearchItem]:
        seen: set[tuple] = set()
        out: list[ResearchItem] = []
        for s in self.sources:
            for it in s.fetch(code, as_of):
                key = (it.title, it.text)
                if key in seen:
                    continue
                seen.add(key)
                out.append(it)
        return out
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_research_sources.py -v`
Expected: PASS（6 个）

- [ ] **Step 5: 提交**

```bash
git add app/research/sources.py tests/test_research_sources.py
git commit -m "feat(research): EastMoneyNewsSource + CompositeSource (dedup)"
```

---

### Task 5: ResearchAnalyzer（LLM 消化为 AnalyzedNote）

**Files:**
- Create: `backend/app/research/analyzer.py`
- Test: `backend/tests/test_research_analyzer.py`（新建）

说明:复用 `app.decision.llm.parse_verdict` 解析 LLM 输出的 JSON。`AnalyzedNote` 从 store.py import。

- [ ] **Step 1: 写失败测试**

新建 `backend/tests/test_research_analyzer.py`:

```python
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
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_research_analyzer.py -v`
Expected: FAIL（`ModuleNotFoundError: app.research.analyzer`）

- [ ] **Step 3: 实现**

新建 `backend/app/research/analyzer.py`:

```python
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
```

注意:`parse_verdict` 的正则 `\{[^{}]*\}` 只匹配不含嵌套花括号的 JSON 对象,本任务输出的 JSON 是扁平的,匹配没问题。

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_research_analyzer.py -v`
Expected: PASS（4 个）

- [ ] **Step 5: 提交**

```bash
git add app/research/analyzer.py tests/test_research_analyzer.py
git commit -m "feat(research): ResearchAnalyzer (LLM -> AnalyzedNote, neutral fallbacks)"
```

---

### Task 6: ResearchRunner（universe 逐只 抓→析→存）

**Files:**
- Create: `backend/app/research/runner.py`
- Test: `backend/tests/test_research_runner.py`（新建）

- [ ] **Step 1: 写失败测试**

新建 `backend/tests/test_research_runner.py`:

用 conftest 的 `session` fixture:

```python
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
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_research_runner.py -v`
Expected: FAIL（`ModuleNotFoundError: app.research.runner`）

- [ ] **Step 3: 实现**

新建 `backend/app/research/runner.py`:

```python
from datetime import date


class ResearchRunner:
    def __init__(self, source, analyzer, store):
        self.source = source
        self.analyzer = analyzer
        self.store = store

    def run(self, universe: set[str], as_of: date) -> int:
        n = 0
        for code in sorted(universe):
            try:
                items = self.source.fetch(code, as_of)
                note = self.analyzer.analyze(code, items)
                self.store.upsert(code, as_of, note,
                                  items[0].source if items else "none")
                n += 1
            except Exception:
                continue  # 单只失败不阻断其余
        return n
```

注意:测试里 `FakeSource` 返回的 item 是裸 `object()`,没有 `.source`;但 `FakeAnalyzer` 不报错,落库走 `items[0].source` → `object` 无 source 属性会抛 `AttributeError`。为避免:`run` 里取 source 用 `getattr`。修正实现的 upsert 行为:

```python
                src = getattr(items[0], "source", "none") if items else "none"
                self.store.upsert(code, as_of, note, src)
```

（用 `getattr` 替换上面的 `items[0].source if items else "none"`。）

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_research_runner.py -v`
Expected: PASS（3 个）

- [ ] **Step 5: 提交**

```bash
git add app/research/runner.py tests/test_research_runner.py
git commit -m "feat(research): ResearchRunner (per-code fetch->analyze->persist, fault-isolated)"
```

---

### Task 7: scorer 改造 —— 并集 + 缺失因子中性 0.5 填充

**Files:**
- Modify: `backend/app/discovery/scorer.py`
- Test: `backend/tests/test_discovery_scorer.py`（改写 1 个、新增 2 个)

说明:这是行为变更。`test_scorer_requires_full_coverage` 断言的是旧交集语义,必须改写为新并集语义。新增「动量场景回归」锁定:全因子齐全时结果与旧版一致。

- [ ] **Step 1: 改写/新增测试**

替换 `backend/tests/test_discovery_scorer.py` 中的 `test_scorer_requires_full_coverage` 为:

```python
def test_scorer_uses_union_with_neutral_fill():
    # b 缺 f2 → f2 按中性 0.5 计;a 两因子齐全
    factors = {"f1": {"a": 1.0, "b": 2.0}, "f2": {"a": 5.0}}
    picks = DiscoveryScorer(top_n=8).score(factors)
    codes = [p[0] for p in picks]
    assert set(codes) == {"a", "b"}  # 并集,两只都进
```

并在文件末尾新增两个:

```python
def test_scorer_momentum_only_matches_intersection_regression():
    # 所有因子覆盖全部 code 时,并集==交集,排名与旧行为一致
    factors = {
        "f1": {"a": 1.0, "b": 2.0, "c": 3.0},
        "f2": {"a": 1.0, "b": 2.0, "c": 3.0},
    }
    picks = DiscoveryScorer(top_n=3).score(factors)
    assert [p[0] for p in picks] == ["c", "b", "a"]


def test_scorer_sparse_factor_neutral_does_not_penalize():
    # 稀疏研报因子:只有 c 有正情绪,a/b 缺该因子按 0.5
    factors = {
        "mom": {"a": 0.5, "b": 0.5, "c": 0.5},     # 动量持平
        "research_sent": {"c": 1.0},                # 只有 c 有研报
    }
    picks = DiscoveryScorer(top_n=3).score(factors)
    assert picks[0][0] == "c"  # 有正研报的 c 排第一
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_discovery_scorer.py -v`
Expected: FAIL（旧 score 用交集,`test_scorer_uses_union_with_neutral_fill` 与稀疏测试失败）

- [ ] **Step 3: 实现**

替换 `backend/app/discovery/scorer.py` 中 `DiscoveryScorer.score` 方法体为:

```python
    def score(self, factors: dict[str, dict[str, float]]):
        """factors: {factor_name: {code: raw}}. 并集所有 code;某 code 缺某
        因子时,该因子百分位按中性 0.5 计入。返回 (code, total, {factor: raw})
        按总分降序,截断 top_n。raw 只含该 code 实际拥有的因子。"""
        if not factors:
            return []
        names = list(factors.keys())
        weights = self.weights or {n: 1.0 / len(names) for n in names}
        pct = {n: percentile_rank(factors[n]) for n in names}
        universe: set[str] = set()
        for n in names:
            universe |= set(factors[n])
        scored = []
        for code in universe:
            total = sum(weights.get(n, 0.0) * pct[n].get(code, 0.5) for n in names)
            raw = {n: factors[n][code] for n in names if code in factors[n]}
            scored.append((code, total, raw))
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[: self.top_n]
```

（`percentile_rank` 函数不变。）

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_discovery_scorer.py tests/test_discovery_runner.py tests/test_momentum_provider.py -v`
Expected: PASS（含发现引擎相关全绿,确认没回归打挂 runner）

- [ ] **Step 5: 提交**

```bash
git add app/discovery/scorer.py tests/test_discovery_scorer.py
git commit -m "feat(discovery): scorer union + neutral 0.5 fill for sparse factors"
```

---

### Task 8: ResearchSignalProvider（读 store → 稀疏 research_sent 因子）

**Files:**
- Create: `backend/app/research/signal.py`
- Test: `backend/tests/test_research_signal.py`（新建）

说明:`SignalProvider.compute(snapshot)` 返回 `{factor: {code: raw}}`。研报 provider 对 snapshot 内每个 code 查 store.latest,有笔记才给值(稀疏)。

- [ ] **Step 1: 写失败测试**

新建 `backend/tests/test_research_signal.py`:

用 conftest 的 `session` fixture:

```python
from datetime import date
from app.research.store import ResearchStore, AnalyzedNote
from app.research.signal import ResearchSignalProvider
from app.discovery.snapshot import StockData


def _snap(*codes):
    return {c: StockData(c, [10.0], [10.0], [1.0], None) for c in codes}


def test_provider_returns_sentiment_only_for_covered(session):
    st = ResearchStore(session)
    st.upsert("600519.SH", date(2026, 6, 3), AnalyzedNote(0.8, "", "x"), "s")
    out = ResearchSignalProvider(st).compute(_snap("600519.SH", "000001.SZ"))
    assert out["research_sent"] == {"600519.SH": 0.8}  # 000001 无笔记不出现


def test_provider_empty_when_no_notes(session):
    out = ResearchSignalProvider(ResearchStore(session)).compute(_snap("000001.SZ"))
    assert out == {"research_sent": {}}
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_research_signal.py -v`
Expected: FAIL（`ModuleNotFoundError: app.research.signal`）

- [ ] **Step 3: 实现**

新建 `backend/app/research/signal.py`:

```python
from app.discovery.providers import SignalProvider
from app.discovery.snapshot import StockData
from app.research.store import ResearchStore


class ResearchSignalProvider(SignalProvider):
    def __init__(self, store: ResearchStore):
        self.store = store

    def compute(self, snapshot: dict[str, StockData]) -> dict[str, dict[str, float]]:
        sent: dict[str, float] = {}
        for code in snapshot:
            note = self.store.latest(code)
            if note is not None:
                sent[code] = note.sentiment
        return {"research_sent": sent}
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_research_signal.py -v`
Expected: PASS（2 个）

- [ ] **Step 5: 提交**

```bash
git add app/research/signal.py tests/test_research_signal.py
git commit -m "feat(research): ResearchSignalProvider (sparse research_sent factor)"
```

---

### Task 9: 接入 run_discovery 脚本（可选挂研报信号）

**Files:**
- Modify: `backend/scripts/run_discovery.py`
- Test: 无新单测（脚本层;逻辑已被 Task 7/8 单测覆盖）。手动 import 校验。

说明:加 `--with-research` 开关;开启时把 `ResearchSignalProvider(ResearchStore(session))` 与 `MomentumProvider` 一起传给 runner。默认关闭,保持现有行为。

- [ ] **Step 1: 实现**

修改 `backend/scripts/run_discovery.py`:

import 区追加:

```python
from app.research.store import ResearchStore
from app.research.signal import ResearchSignalProvider
```

`argparse` 区追加:

```python
    p.add_argument("--with-research", action="store_true",
                   help="挂入研报质化信号(读 research_notes)")
```

把构造 runner 的那段改为:

```python
    providers = [MomentumProvider()]
    if args.with_research:
        providers.append(ResearchSignalProvider(ResearchStore(session)))
    runner = DiscoveryRunner(session, QuoteStoreMarketHistory(store),
                             providers, DiscoveryScorer(top_n=8),
                             window=args.window)
```

- [ ] **Step 2: import/语法校验**

Run: `.venv/bin/python -c "import ast; ast.parse(open('scripts/run_discovery.py').read()); print('ok')"`
Expected: `ok`

- [ ] **Step 3: 全量测试确保无回归**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS（截至此任务全绿）

- [ ] **Step 4: 提交**

```bash
git add scripts/run_discovery.py
git commit -m "feat(scripts): run_discovery --with-research to plug in qualitative signal"
```

---

### Task 10: 决策 brief 加研报段

**Files:**
- Modify: `backend/app/decision/brief.py`
- Test: `backend/tests/test_brief.py`（追加）

说明:`build_brief` 加第 6 个参数 `research=None`(默认 None,现有 5 参调用不破)。`research` 形如 `{"sentiment": float, "rating_consensus": str, "summary": str}`。

- [ ] **Step 1: 写失败测试**

先看现有 `tests/test_brief.py` 的风格,再追加:

```python
def test_brief_renders_research_section():
    b = build_brief("X", [10.0, 11.0], {}, {},
                    holding=None,
                    research={"sentiment": 0.6, "rating_consensus": "买入",
                              "summary": "机构看多"})
    p = b.to_prompt()
    assert "研报" in p and "机构看多" in p and "0.6" in p


def test_brief_research_absent_says_no_data():
    b = build_brief("X", [10.0], {}, {}, holding=None)
    assert "无研报数据" in b.to_prompt()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_brief.py -v`
Expected: FAIL（`build_brief` 不接受 `research` / prompt 无研报段）

- [ ] **Step 3: 实现**

修改 `backend/app/decision/brief.py`。

`StockBrief` dataclass 加字段（在 `holding` 之后）:

```python
    research: dict | None = None
```

`to_prompt` 在 `f"{hold}\n"` 之前插入研报段。把 return 改为:

```python
        if self.research:
            r = self.research
            research_line = (
                f"研报观点: 情绪分={r.get('sentiment')} "
                f"评级={r.get('rating_consensus','')} "
                f"摘要={r.get('summary','')}\n")
        else:
            research_line = "研报观点: 无研报数据\n"
        return (
            f"股票代码: {self.code}\n"
            f"最新收盘: {last}\n"
            f"近期收盘序列: {self.recent_closes}\n"
            f"量价因子: {json.dumps(self.factors, ensure_ascii=False)}\n"
            f"基本面: {json.dumps(self.fundamentals, ensure_ascii=False)}\n"
            f"{research_line}"
            f"{hold}\n"
        )
```

`build_brief` 签名与返回:

```python
def build_brief(code, recent_closes, factors, fundamentals, holding,
                research=None) -> StockBrief:
    return StockBrief(code=code, recent_closes=list(recent_closes),
                      factors=dict(factors), fundamentals=dict(fundamentals),
                      holding=holding, research=research)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_brief.py tests/test_decision_graph.py -v`
Expected: PASS（含 graph 测试,确认 brief 变更不破辩论流程）

- [ ] **Step 5: 提交**

```bash
git add app/decision/brief.py tests/test_brief.py
git commit -m "feat(decision): StockBrief research section for the 新闻研报分析师"
```

---

### Task 11: 新闻研报分析师 role + 接入 run_decisions

**Files:**
- Modify: `backend/app/decision/agents.py`（更新 role prompt）
- Modify: `backend/scripts/run_decisions.py`（填 research 数据）
- Test: `backend/tests/test_decision_agents.py`（追加断言）

说明:role prompt 改为引导基于 brief 研报段表态;run_decisions 用 `ResearchStore.latest(code)` 填 `build_brief` 的 research 参数。

- [ ] **Step 1: 写失败测试**

追加到 `backend/tests/test_decision_agents.py`:

```python
def test_news_research_role_mentions_research():
    from app.decision.agents import ROLES
    role = ROLES["新闻研报分析师"]
    assert "研报" in role
    # 不再是"当前无研报数据"的死 stub 措辞
    assert "当前无研报数据时直接说明" not in role
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_decision_agents.py::test_news_research_role_mentions_research -v`
Expected: FAIL（现有 prompt 含旧措辞)

- [ ] **Step 3: 实现**

修改 `backend/app/decision/agents.py` 中 `ROLES["新闻研报分析师"]` 为:

```python
    "新闻研报分析师": ("你是新闻/研报分析师。依据 brief 中的「研报观点」"
                       "(情绪分/评级/摘要)给出对该股的判断;若显示无研报数据"
                       "则说明数据缺失并保持中性。结尾输出 JSON: "
                       '{"stance": "bull|bear|neutral", "confidence": <0-1>}'),
```

（保持与其他 role 一致的 JSON verdict 结尾;参考同文件其它 role 的格式。若其它 role 的 verdict 字段不同,以同文件现有约定为准——本步只需让 prompt 含「研报」且去掉旧 stub 措辞。)

修改 `backend/scripts/run_decisions.py`:

import 区追加:

```python
from app.research.store import ResearchStore
```

在 `store = QuoteStore(session)` 之后追加:

```python
    research = ResearchStore(session)
```

把 build_brief 调用改为带 research:

```python
        rnote = research.latest(code)
        r = ({"sentiment": rnote.sentiment,
              "rating_consensus": rnote.rating_consensus,
              "summary": rnote.summary} if rnote else None)
        briefs.append(build_brief(code, closes, {}, {}, holding, research=r))
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_decision_agents.py tests/test_decision_graph.py -v`
并校验脚本语法:`.venv/bin/python -c "import ast; ast.parse(open('scripts/run_decisions.py').read()); print('ok')"`
Expected: 测试 PASS;`ok`

- [ ] **Step 5: 提交**

```bash
git add app/decision/agents.py scripts/run_decisions.py tests/test_decision_agents.py
git commit -m "feat(decision): wire research notes into 新闻研报分析师 + run_decisions"
```

---

### Task 12: API GET /api/research/{code}

**Files:**
- Create: `backend/app/api/routes_research.py`
- Modify: `backend/app/main.py`（注册 router）
- Test: `backend/tests/test_api_research.py`（新建）

说明:依赖注入照搬 `app/api/routes_discovery.py`:session 来自 `app.api.deps.get_session`,router 用 `prefix="/api"`。测试用 `create_app()` + `app.dependency_overrides` + StaticPool(与 `test_api_discovery.py` 一致)。

- [ ] **Step 1: 写失败测试**

新建 `backend/tests/test_api_research.py`(照搬 `test_api_discovery.py` 的 client 构造):

```python
from datetime import date
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.db.database import Base
import app.db.models  # noqa
from app.main import create_app
from app.api.deps import get_session
from app.research.store import ResearchStore, AnalyzedNote


def _client():
    engine = create_engine("sqlite:///:memory:", future=True,
                           connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, expire_on_commit=False, future=True)()
    ResearchStore(s).upsert("600519.SH", date(2026, 6, 3),
                            AnalyzedNote(0.5, "买入", "稳"), "tushare")
    app = create_app()
    app.dependency_overrides[get_session] = lambda: s
    return TestClient(app)


def test_get_research_returns_latest():
    r = _client().get("/api/research/600519.SH")
    assert r.status_code == 200
    assert r.json()["sentiment"] == 0.5 and r.json()["summary"] == "稳"


def test_get_research_404_when_absent():
    r = _client().get("/api/research/999999.SZ")
    assert r.status_code == 404
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_api_research.py -v`
Expected: FAIL（404 路由不存在 / import 失败)

- [ ] **Step 3: 实现**

新建 `backend/app/api/routes_research.py`（依赖注入照搬 `routes_discovery.py`,`get_session` 来自 `app.api.deps`,prefix `/api`）:

```python
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.api.deps import get_session
from app.research.store import ResearchStore

router = APIRouter(prefix="/api", tags=["research"])


@router.get("/research/{code}")
def get_research(code: str, s: Session = Depends(get_session)):
    note = ResearchStore(s).latest(code)
    if note is None:
        raise HTTPException(status_code=404, detail="no research note")
    return {"code": note.code, "as_of": note.as_of.isoformat(),
            "sentiment": note.sentiment,
            "rating_consensus": note.rating_consensus,
            "summary": note.summary, "source": note.source}
```

在 `backend/app/main.py` 注册:import 行追加 `routes_research`,并加 `app.include_router(routes_research.router)`。

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_api_research.py -v`
Expected: PASS（2 个）

- [ ] **Step 5: 提交**

```bash
git add app/api/routes_research.py app/main.py tests/test_api_research.py
git commit -m "feat(api): GET /api/research/{code} latest note"
```

---

### Task 13: run_research.py 日度脚本

**Files:**
- Create: `backend/scripts/run_research.py`
- Test: 无单测(脚本层;runner/source/analyzer 已被单测覆盖)。语法+import 校验。

说明:组装 universe = 持仓 ∪ 最新 discovery_picks ∪ watch_pool;按 `research_llm` 选 LLM;tushare source 带 RateLimiter(`research_max_per_min`)。

- [ ] **Step 1: 实现**

新建 `backend/scripts/run_research.py`:

```python
import sys
from pathlib import Path
from datetime import date

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select, func
from app.config import get_settings
from app.db.database import make_engine, make_session_factory, Base
import app.db.models  # noqa: F401
from app.db.models import Position, DiscoveryPick, WatchPoolEntry
from app.data.quote_store import QuoteStore
from app.data.rate_limiter import RateLimiter
from app.decision.llm import LocalClaudeClient, DeepSeekClient
from app.research.sources import (TushareResearchSource, EastMoneyNewsSource,
                                  CompositeSource)
from app.research.analyzer import ResearchAnalyzer
from app.research.store import ResearchStore
from app.research.runner import ResearchRunner


def _llm(s):
    if s.research_llm == "deepseek":
        return DeepSeekClient(s.deepseek_api_key, s.deepseek_base_url, s.deepseek_model)
    return LocalClaudeClient(bin_path=s.claude_bin)


def main():
    s = get_settings()
    engine = make_engine(); Base.metadata.create_all(engine)
    session = make_session_factory(engine)()
    store = QuoteStore(session)
    as_of = store.trading_dates(date.today(), 1)[0]

    holds = {p.code for p in session.scalars(select(Position)).all()}
    top_date = session.scalar(select(func.max(DiscoveryPick.as_of)))
    top = {r.code for r in session.scalars(
        select(DiscoveryPick).where(DiscoveryPick.as_of == top_date)).all()} \
        if top_date else set()
    watch = {w.code for w in session.scalars(select(WatchPoolEntry)).all()}
    universe = holds | top | watch

    import tushare as ts
    pro = ts.pro_api(s.tushare_token)
    limiter = RateLimiter(max_calls=s.research_max_per_min, period_s=60.0)
    source = CompositeSource([
        TushareResearchSource(pro, limiter=limiter),
        EastMoneyNewsSource(),
    ])
    runner = ResearchRunner(source, ResearchAnalyzer(_llm(s)), ResearchStore(session))
    n = runner.run(universe, as_of)
    print(f"RESEARCH_DONE as_of={as_of} universe={len(universe)} written={n}",
          flush=True)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 语法+import 校验**

Run: `.venv/bin/python -c "import ast; ast.parse(open('scripts/run_research.py').read()); print('ok')"`
Expected: `ok`

- [ ] **Step 3: 全量测试**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS（全绿)

- [ ] **Step 4: 提交**

```bash
git add scripts/run_research.py
git commit -m "feat(scripts): run_research daily runner (universe -> notes)"
```

---

### Task 14: 冒烟验证 + 接通 EastMoney 真实端点 + README

**Files:**
- Modify: `backend/app/research/sources.py`（`_em_default_fetch` 接真实端点)
- Modify: `README.md`（研报模块章节 + 测试数 108→更新)
- Test: 真实接口冒烟(手动,不入 CI)

说明:此前所有任务用 fake,真实联调放最后。EastMoney 端点沿用 screener `datacenter_board_members` 的 requests+重试模式;若联调发现该源不可用,保留 `EastMoneyNewsSource` 但 universe 仅靠 tushare 也可跑(CompositeSource 容错)。

- [ ] **Step 1: 接 EastMoney 真实抓取**

把 `app/research/sources.py` 的 `_em_default_fetch` 实现为基于 `requests` 的真实抓取(参考 `app/screener/themes.py::datacenter_board_members` 的 header/重试/超时写法)。若联调确认 egress 被封,则让其 `return []`(降级,不抛),并在 README 注明。

- [ ] **Step 2: 真实冒烟(1-2 只股)**

Run（需 `.env` 配好 tushare_token;LLM 默认本地 Claude）:

```bash
cd backend
.venv/bin/python -c "
from datetime import date
from app.config import get_settings
import tushare as ts
from app.research.sources import TushareResearchSource
s=get_settings(); pro=ts.pro_api(s.tushare_token)
items=TushareResearchSource(pro).fetch('600519.SH', date.today())
print('tushare items:', len(items))
for i in items[:3]: print(i.title, i.rating)
"
```
Expected: 打印若干 tushare 研报条目(条数>0 或合理为 0);无异常。

再跑一只股全链路(本地 Claude 较慢,单只即可):

```bash
.venv/bin/python -c "
from datetime import date
from app.config import get_settings
from app.db.database import make_engine, make_session_factory, Base
import app.db.models, tushare as ts
from app.data.quote_store import QuoteStore
from app.research.sources import TushareResearchSource
from app.research.analyzer import ResearchAnalyzer
from app.research.store import ResearchStore
from app.research.runner import ResearchRunner
from app.decision.llm import LocalClaudeClient
s=get_settings()
e=make_engine(); Base.metadata.create_all(e); sess=make_session_factory(e)()
pro=ts.pro_api(s.tushare_token)
r=ResearchRunner(TushareResearchSource(pro), ResearchAnalyzer(LocalClaudeClient(bin_path=s.claude_bin)), ResearchStore(sess))
print('written:', r.run({'600519.SH'}, date.today()))
print('note:', ResearchStore(sess).latest('600519.SH').summary[:200])
"
```
Expected: `written: 1`;打印一段合理的中文摘要。人工核对摘要与情绪分是否合理。

- [ ] **Step 3: 全量测试 + README**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS（全绿）

在 `README.md` 加「## Research analysis (研报情绪信号)」章节:说明数据源(tushare report_rc+news / eastmoney 新闻)、LLM 可配(默认本地 Claude)、`research_notes` 缓存、`run_research.py` 用法、`run_discovery --with-research` 挂信号、`GET /api/research/{code}`。并把测试总数注释更新为新值(运行 `pytest -q` 末行的实际数)。

- [ ] **Step 4: 提交**

```bash
git add app/research/sources.py README.md
git commit -m "feat(research): wire real eastmoney fetch + smoke-verified + README"
```

---

## 完成标准

- 全量 `pytest -q` 全绿(新增约 20+ 测试)。
- `run_research.py` 真实冒烟跑通 1 只股,摘要合理。
- `run_discovery --with-research` 能挂入研报因子且不破坏纯动量回归。
- 决策 brief 含研报段,新闻研报分析师读到数据。
- 分支 `slice-4`,逐任务提交,待用户决定合并/推送(PAT 见项目记忆)。
