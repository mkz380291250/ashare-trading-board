# Slice 3: Multi-Agent Decision Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A weekly multi-agent decision engine (analysts → bull/bear debate → trader → risk committee) that recommends BUY/SELL/HOLD per stock (holdings ∪ discovery Top-8), pending user approval that triggers the PaperBroker.

**Architecture:** New `backend/app/decision/` module. A pluggable `LLMClient` (default `LocalClaudeClient` via `claude -p`, alt `DeepSeekClient`) drives agent roles whose prompts are ported from TradingAgents-CN. A `DecisionGraph` orchestrates the debate over a `StockBrief` (built from QuoteStore + discovery factors + tushare fundamentals + holding) and emits a parsed verdict. `DecisionRunner` persists PENDING `decisions`; the API approves → trades.

**Tech Stack:** Python 3.11, SQLAlchemy 2.x, pytest, requests, subprocess; React+Vite+TS. Reuses QuoteStore, discovery factors, PaperBroker.

---

## Reference: Spec

`docs/superpowers/specs/2026-06-02-slice-3-decision-engine-design.md`. LLM default
local Claude; full role set; target = holdings ∪ Top-8; 财报 in, 研报 stub for slice 4;
每个 agent 末尾给 JSON verdict; 人机审批后 PaperBroker 执行。

## File Structure

```
backend/
  app/
    decision/
      __init__.py
      llm.py        # NEW: LLMClient ABC, LocalClaudeClient, DeepSeekClient, parse_verdict
      brief.py      # NEW: StockBrief dataclass + build_brief
      agents.py     # NEW: AgentReport, Agent, role system prompts
      graph.py      # NEW: Decision dataclass, DecisionGraph.run
      runner.py     # NEW: DecisionRunner
    db/models.py    # MODIFY: add Decision
    config.py       # MODIFY: decision_llm, claude_bin
    api/routes_decisions.py  # NEW: list/approve/reject
    main.py         # MODIFY: include router
  scripts/run_decisions.py   # NEW
  tests/
    test_parse_verdict.py
    test_llm_clients.py
    test_brief.py
    test_decision_agents.py
    test_decision_graph.py
    test_decision_runner.py
    test_api_decisions.py
frontend/src/components/DecisionsPanel.tsx  # NEW
frontend/src/pages/Dashboard.tsx            # MODIFY
```

---

## Task 1: Decision model

**Files:**
- Modify: `backend/app/db/models.py`
- Test: `backend/tests/test_decision_models.py`

- [ ] **Step 1: Write failing test `backend/tests/test_decision_models.py`**

```python
from datetime import date
from app.db.models import Decision


def test_decision_roundtrip(session):
    d = Decision(as_of=date(2026, 5, 29), code="600519.SH", action="BUY",
                 confidence=0.7, shares=100, reasoning="**bull** wins", status="PENDING")
    session.add(d); session.commit()
    got = session.query(Decision).one()
    assert got.code == "600519.SH" and got.action == "BUY"
    assert got.status == "PENDING" and got.shares == 100
```

- [ ] **Step 2: Run test, expect failure**

Run (from `backend/`): `.venv/bin/python -m pytest tests/test_decision_models.py -v`
Expected: FAIL — `ImportError: cannot import name 'Decision'`.

- [ ] **Step 3: Append to `backend/app/db/models.py`**

```python
class Decision(Base):
    __tablename__ = "decisions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    as_of: Mapped[date] = mapped_column(Date)
    code: Mapped[str] = mapped_column(String(16))
    action: Mapped[str] = mapped_column(String(8))   # BUY/SELL/HOLD
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    shares: Mapped[int] = mapped_column(Integer, default=0)
    reasoning: Mapped[str] = mapped_column(String, default="")
    status: Mapped[str] = mapped_column(String(10), default="PENDING")
    created_at: Mapped[date] = mapped_column(Date)


Index("ix_decisions_as_of", Decision.as_of)
```

(`Index`, `Integer`, `Date`, `String`, `Float`, `Mapped`, `mapped_column` already imported.)

- [ ] **Step 4: Run test, expect pass**

Run: `.venv/bin/python -m pytest tests/test_decision_models.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/db/models.py backend/tests/test_decision_models.py
git commit -m "feat(decision): Decision model (PENDING/APPROVED/REJECTED)"
```

---

## Task 2: parse_verdict + LLMClient interface

**Files:**
- Create: `backend/app/decision/__init__.py`, `backend/app/decision/llm.py`
- Test: `backend/tests/test_parse_verdict.py`

- [ ] **Step 1: Write failing test `backend/tests/test_parse_verdict.py`**

```python
from app.decision.llm import parse_verdict


def test_extracts_last_fenced_json():
    text = ('分析... ```json\n{"action": "SELL", "confidence": 0.3}\n```\n'
            '结论 ```json\n{"action": "BUY", "confidence": 0.8, "shares": 50}\n```')
    v = parse_verdict(text)
    assert v == {"action": "BUY", "confidence": 0.8, "shares": 50}


def test_bare_json_object():
    assert parse_verdict('blah {"stance": "bull", "confidence": 0.6} end') == \
        {"stance": "bull", "confidence": 0.6}


def test_missing_or_invalid_returns_empty():
    assert parse_verdict("no json here") == {}
    assert parse_verdict("broken {not json}") == {}
```

- [ ] **Step 2: Run test, expect failure**

Run: `.venv/bin/python -m pytest tests/test_parse_verdict.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Write `backend/app/decision/llm.py`**

```python
import json
import re
import subprocess
from abc import ABC, abstractmethod

_JSON_RE = re.compile(r"\{[^{}]*\}")


def parse_verdict(text: str) -> dict:
    """Return the LAST JSON object found in text (fenced or bare), else {}."""
    matches = _JSON_RE.findall(text or "")
    for chunk in reversed(matches):
        try:
            obj = json.loads(chunk)
            if isinstance(obj, dict):
                return obj
        except Exception:
            continue
    return {}


class LLMClient(ABC):
    @abstractmethod
    def complete(self, prompt: str, system: str | None = None) -> str:
        ...


class LocalClaudeClient(LLMClient):
    """Headless local Claude via `claude -p`."""

    def __init__(self, bin_path: str = "/usr/local/bin/claude",
                 timeout: int = 300, run=subprocess.run):
        self.bin = bin_path
        self.timeout = timeout
        self._run = run

    def complete(self, prompt: str, system: str | None = None) -> str:
        full = prompt if not system else f"{system}\n\n{prompt}"
        r = self._run([self.bin, "-p", full, "--output-format", "text"],
                      capture_output=True, text=True, timeout=self.timeout)
        return (r.stdout or "").strip()


class DeepSeekClient(LLMClient):
    def __init__(self, api_key: str, base_url: str, model: str, post=None):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        if post is None:
            import requests
            post = requests.post
        self._post = post

    def complete(self, prompt: str, system: str | None = None) -> str:
        msgs = ([{"role": "system", "content": system}] if system else []) + \
               [{"role": "user", "content": prompt}]
        r = self._post(f"{self.base_url}/chat/completions",
                       headers={"Authorization": f"Bearer {self.api_key}"},
                       json={"model": self.model, "messages": msgs}, timeout=120)
        return r.json()["choices"][0]["message"]["content"].strip()
```

Create empty `backend/app/decision/__init__.py`.

- [ ] **Step 4: Run test, expect pass**

Run: `.venv/bin/python -m pytest tests/test_parse_verdict.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/app/decision/__init__.py backend/app/decision/llm.py backend/tests/test_parse_verdict.py
git commit -m "feat(decision): parse_verdict + LLMClient (LocalClaude default, DeepSeek alt)"
```

---

## Task 3: LLMClient impls (subprocess / HTTP, mocked)

**Files:**
- Test: `backend/tests/test_llm_clients.py`

(No new code — tests the Task 2 clients with injected fakes.)

- [ ] **Step 1: Write failing test `backend/tests/test_llm_clients.py`**

```python
from app.decision.llm import LocalClaudeClient, DeepSeekClient


class _Proc:
    def __init__(self, out): self.stdout = out; self.returncode = 0


def test_local_claude_invokes_binary_and_returns_stdout():
    calls = {}

    def fake_run(cmd, **kw):
        calls["cmd"] = cmd
        return _Proc("HELLO\n")

    c = LocalClaudeClient(bin_path="/x/claude", run=fake_run)
    out = c.complete("hi", system="be brief")
    assert out == "HELLO"
    assert calls["cmd"][0] == "/x/claude" and "-p" in calls["cmd"]
    assert "be brief" in calls["cmd"][calls["cmd"].index("-p") + 1]


class _Resp:
    def __init__(self, content): self._c = content
    def json(self): return {"choices": [{"message": {"content": self._c}}]}


def test_deepseek_posts_and_parses():
    seen = {}

    def fake_post(url, **kw):
        seen["url"] = url; seen["json"] = kw["json"]
        return _Resp("WORLD")

    c = DeepSeekClient(api_key="k", base_url="https://api.x.com", model="m", post=fake_post)
    assert c.complete("q", system="s") == "WORLD"
    assert seen["url"].endswith("/chat/completions")
    assert seen["json"]["messages"][0]["role"] == "system"
```

- [ ] **Step 2: Run test, expect pass (code already exists)**

Run: `.venv/bin/python -m pytest tests/test_llm_clients.py -v`
Expected: PASS (2 tests). If FAIL, fix `llm.py` from Task 2.

- [ ] **Step 3: Commit**

```bash
git add backend/tests/test_llm_clients.py
git commit -m "test(decision): LocalClaude/DeepSeek client behavior with injected fakes"
```

---

## Task 4: StockBrief + build_brief

**Files:**
- Create: `backend/app/decision/brief.py`
- Test: `backend/tests/test_brief.py`

- [ ] **Step 1: Write failing test `backend/tests/test_brief.py`**

```python
from app.decision.brief import StockBrief, build_brief


def test_build_brief_assembles_prompt():
    brief = build_brief(
        code="600519.SH",
        recent_closes=[1000.0, 1010.0, 1050.0],
        factors={"mom_5d": 0.05, "turnover": 2.0, "vol_ratio": 1.8, "breakout": 0.99},
        fundamentals={"np_yoy": 25.0, "rev_yoy": 12.0, "pe": 30.0, "pb": 9.0},
        holding={"shares": 100, "cost": 980.0},
    )
    assert isinstance(brief, StockBrief)
    p = brief.to_prompt()
    assert "600519.SH" in p
    assert "mom_5d" in p and "0.05" in p
    assert "np_yoy" in p and "25" in p
    assert "持仓" in p and "100" in p  # holding shown


def test_brief_no_holding():
    brief = build_brief("X", [1.0], {}, {}, holding=None)
    assert "无持仓" in brief.to_prompt()
```

- [ ] **Step 2: Run test, expect failure**

Run: `.venv/bin/python -m pytest tests/test_brief.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Write `backend/app/decision/brief.py`**

```python
import json
from dataclasses import dataclass


@dataclass(frozen=True)
class StockBrief:
    code: str
    recent_closes: list[float]
    factors: dict
    fundamentals: dict
    holding: dict | None

    def to_prompt(self) -> str:
        last = self.recent_closes[-1] if self.recent_closes else None
        if self.holding:
            hold = f"持仓 {self.holding.get('shares')} 股,成本 {self.holding.get('cost')}"
        else:
            hold = "无持仓"
        return (
            f"股票代码: {self.code}\n"
            f"最新收盘: {last}\n"
            f"近期收盘序列: {self.recent_closes}\n"
            f"量价因子: {json.dumps(self.factors, ensure_ascii=False)}\n"
            f"基本面: {json.dumps(self.fundamentals, ensure_ascii=False)}\n"
            f"{hold}\n"
        )


def build_brief(code, recent_closes, factors, fundamentals, holding) -> StockBrief:
    return StockBrief(code=code, recent_closes=list(recent_closes),
                      factors=dict(factors), fundamentals=dict(fundamentals),
                      holding=holding)
```

- [ ] **Step 4: Run test, expect pass**

Run: `.venv/bin/python -m pytest tests/test_brief.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/app/decision/brief.py backend/tests/test_brief.py
git commit -m "feat(decision): StockBrief + build_brief (prompt assembly)"
```

---

## Task 5: Agent + role prompts

**Files:**
- Create: `backend/app/decision/agents.py`
- Test: `backend/tests/test_decision_agents.py`

- [ ] **Step 1: Write failing test `backend/tests/test_decision_agents.py`**

```python
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
```

- [ ] **Step 2: Run test, expect failure**

Run: `.venv/bin/python -m pytest tests/test_decision_agents.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Write `backend/app/decision/agents.py`**

```python
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
    "量价分析师": "你是A股量价技术分析师。基于价格序列与量价因子(动量/换手/量比/突破)"
    "分析趋势与强度,简明给出看法。结尾输出 ```json {\"stance\":\"bull|bear|neutral\","
    "\"confidence\":0-1} ```。",
    "基本面分析师": "你是A股基本面分析师。基于净利/营收增速、PE/PB 评估质量与估值。"
    "结尾输出 ```json {\"stance\":\"bull|bear|neutral\",\"confidence\":0-1} ```。",
    "新闻研报分析师": "你是新闻/研报分析师。当前无研报数据时直接说明数据缺失并保持中性。"
    "结尾输出 ```json {\"stance\":\"neutral\",\"confidence\":0} ```。",
    "多头研究员": "你是多头研究员。综合分析师观点与空头上轮论点,论证买入理由。"
    "结尾输出 ```json {\"stance\":\"bull\",\"confidence\":0-1} ```。",
    "空头研究员": "你是空头研究员。综合分析师观点与多头上轮论点,论证风险与卖出理由。"
    "结尾输出 ```json {\"stance\":\"bear\",\"confidence\":0-1} ```。",
    "交易员": "你是交易员。综合分析师与多空辩论,给出 BUY/SELL/HOLD 草案与建议股数。"
    "结尾输出 ```json {\"action\":\"BUY|SELL|HOLD\",\"confidence\":0-1,\"shares\":int} ```。",
    "激进风控": "你是激进派风控。倾向把握机会。结尾 ```json {\"stance\":\"aggressive\",\"confidence\":0-1} ```。",
    "保守风控": "你是保守派风控。倾向控制回撤。结尾 ```json {\"stance\":\"conservative\",\"confidence\":0-1} ```。",
    "中性风控": "你是中性派风控。权衡两端。结尾 ```json {\"stance\":\"neutral\",\"confidence\":0-1} ```。",
    "风控经理": "你是风控经理,做最终裁决。综合交易员草案与风控辩论,给出最终决策。"
    "结尾输出 ```json {\"action\":\"BUY|SELL|HOLD\",\"confidence\":0-1,\"shares\":int} ```。",
}
```

- [ ] **Step 4: Run test, expect pass**

Run: `.venv/bin/python -m pytest tests/test_decision_agents.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/app/decision/agents.py backend/tests/test_decision_agents.py
git commit -m "feat(decision): Agent + ported role system prompts (JSON verdicts)"
```

---

## Task 6: DecisionGraph orchestration

**Files:**
- Create: `backend/app/decision/graph.py`
- Test: `backend/tests/test_decision_graph.py`

- [ ] **Step 1: Write failing test `backend/tests/test_decision_graph.py`**

```python
from app.decision.brief import build_brief
from app.decision.graph import DecisionGraph, Decision


class ScriptedLLM:
    """Returns a canned reply keyed by which role's system prompt is seen."""
    def complete(self, prompt, system=None):
        if "交易员" in (system or ""):
            return '草案买入 {"action": "BUY", "confidence": 0.6, "shares": 100}'
        if "风控经理" in (system or ""):
            return '最终批准 {"action": "BUY", "confidence": 0.8, "shares": 100}'
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
```

- [ ] **Step 2: Run test, expect failure**

Run: `.venv/bin/python -m pytest tests/test_decision_graph.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Write `backend/app/decision/graph.py`**

```python
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
        nr = self._agent("新闻研报分析师").run(bp); reports.append(nr)
        analyst_ctx = f"{pv.text}\n{fa.text}\n{nr.text}"

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
```

- [ ] **Step 4: Run test, expect pass**

Run: `.venv/bin/python -m pytest tests/test_decision_graph.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/app/decision/graph.py backend/tests/test_decision_graph.py
git commit -m "feat(decision): DecisionGraph debate orchestration (analysts->debate->trader->risk)"
```

---

## Task 7: DecisionRunner

**Files:**
- Create: `backend/app/decision/runner.py`
- Test: `backend/tests/test_decision_runner.py`

`DecisionRunner.run(as_of, briefs)` runs the graph per brief and upserts PENDING
`decisions` (idempotent per (as_of, code) via delete-then-insert).

- [ ] **Step 1: Write failing test `backend/tests/test_decision_runner.py`**

```python
from datetime import date
from app.db.models import Decision
from app.decision.brief import build_brief
from app.decision.graph import DecisionGraph
from app.decision.runner import DecisionRunner


class ScriptedLLM:
    def complete(self, prompt, system=None):
        if "风控经理" in (system or ""):
            return '{"action": "BUY", "confidence": 0.8, "shares": 100}'
        if "交易员" in (system or ""):
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
```

- [ ] **Step 2: Run test, expect failure**

Run: `.venv/bin/python -m pytest tests/test_decision_runner.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Write `backend/app/decision/runner.py`**

```python
from datetime import date
from sqlalchemy import delete
from sqlalchemy.orm import Session
from app.db.models import Decision
from app.decision.graph import DecisionGraph
from app.decision.brief import StockBrief


class DecisionRunner:
    def __init__(self, session: Session, graph: DecisionGraph):
        self.s = session
        self.graph = graph

    def run(self, as_of: date, briefs: list[StockBrief]) -> list[Decision]:
        out = []
        for brief in briefs:
            d = self.graph.run(brief)
            self.s.execute(delete(Decision).where(
                Decision.as_of == as_of, Decision.code == brief.code))
            row = Decision(as_of=as_of, code=brief.code, action=d.action,
                           confidence=d.confidence, shares=d.shares,
                           reasoning=d.reasoning, status="PENDING", created_at=as_of)
            self.s.add(row); out.append(row)
        self.s.commit()
        return out
```

- [ ] **Step 4: Run test, expect pass**

Run: `.venv/bin/python -m pytest tests/test_decision_runner.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/app/decision/runner.py backend/tests/test_decision_runner.py
git commit -m "feat(decision): DecisionRunner persists PENDING decisions (idempotent)"
```

---

## Task 8: API — list / approve / reject (+ PaperBroker)

**Files:**
- Create: `backend/app/api/routes_decisions.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_api_decisions.py`

Approve executes via PaperBroker at the latest close; needs a price. For the MVP
the approve endpoint accepts an optional `price` (defaults to a `latest_close`
lookup that we keep simple: the request body supplies it). HOLD just marks approved.

- [ ] **Step 1: Write failing test `backend/tests/test_api_decisions.py`**

```python
from datetime import date
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.db.database import Base
import app.db.models  # noqa
from app.db.models import Decision, Account
from app.main import create_app
from app.api.deps import get_session


def _client():
    engine = create_engine("sqlite:///:memory:", future=True,
                           connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, expire_on_commit=False, future=True)()
    s.add(Account(name="main", cash=1000000.0))
    s.add(Decision(as_of=date(2026, 5, 29), code="X", action="BUY", confidence=0.8,
                   shares=100, reasoning="md", status="PENDING", created_at=date(2026, 5, 29)))
    s.commit()
    app = create_app()
    app.dependency_overrides[get_session] = lambda: s
    return TestClient(app), s


def test_list_decisions():
    client, _ = _client()
    data = client.get("/api/decisions").json()
    assert len(data) == 1 and data[0]["action"] == "BUY" and data[0]["status"] == "PENDING"


def test_approve_executes_trade():
    client, s = _client()
    did = s.query(Decision).one().id
    r = client.post(f"/api/decisions/{did}/approve", json={"price": 1000.0})
    assert r.status_code == 200
    assert s.get(Decision, did).status == "APPROVED"
    acc = client.get("/api/account/1").json()
    assert acc["cash"] == 1000000.0 - 1000.0 * 100   # BUY executed
    assert acc["positions"][0]["code"] == "X"


def test_reject_no_trade():
    client, s = _client()
    did = s.query(Decision).one().id
    r = client.post(f"/api/decisions/{did}/reject")
    assert r.status_code == 200
    assert s.get(Decision, did).status == "REJECTED"
    assert client.get("/api/account/1").json()["cash"] == 1000000.0
```

- [ ] **Step 2: Run test, expect failure**

Run: `.venv/bin/python -m pytest tests/test_api_decisions.py -v`
Expected: FAIL — routes missing.

- [ ] **Step 3: Write `backend/app/api/routes_decisions.py`**

```python
from datetime import date as date_t
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from app.api.deps import get_session
from app.db.models import Decision, Account
from app.trading.broker import PaperBroker, InsufficientFunds, InsufficientShares

router = APIRouter(prefix="/api", tags=["decisions"])


class ApproveBody(BaseModel):
    price: float = 0.0
    account_id: int = 1


@router.get("/decisions")
def list_decisions(date: date_t | None = None, s: Session = Depends(get_session)):
    target = date or s.scalar(select(func.max(Decision.as_of)))
    if target is None:
        return []
    rows = s.scalars(select(Decision).where(Decision.as_of == target)
                     .order_by(Decision.code)).all()
    return [{"id": r.id, "as_of": r.as_of.isoformat(), "code": r.code,
             "action": r.action, "confidence": r.confidence, "shares": r.shares,
             "status": r.status, "reasoning": r.reasoning} for r in rows]


@router.post("/decisions/{decision_id}/approve")
def approve(decision_id: int, body: ApproveBody, s: Session = Depends(get_session)):
    d = s.get(Decision, decision_id)
    if d is None:
        raise HTTPException(404, "decision not found")
    if d.status != "PENDING":
        return {"status": d.status}
    if d.action in ("BUY", "SELL") and d.shares > 0:
        broker = PaperBroker(s)
        try:
            if d.action == "BUY":
                broker.buy(body.account_id, d.code, body.price, d.shares, d.as_of)
            else:
                broker.sell(body.account_id, d.code, body.price, d.shares, d.as_of)
        except (InsufficientFunds, InsufficientShares) as e:
            raise HTTPException(400, str(e))
    d.status = "APPROVED"
    s.commit()
    return {"status": "APPROVED"}


@router.post("/decisions/{decision_id}/reject")
def reject(decision_id: int, s: Session = Depends(get_session)):
    d = s.get(Decision, decision_id)
    if d is None:
        raise HTTPException(404, "decision not found")
    d.status = "REJECTED"; s.commit()
    return {"status": "REJECTED"}
```

- [ ] **Step 4: Add router to `backend/app/main.py`**

Extend the import/include block to include `routes_decisions`:
```python
    from app.api import (routes_account, routes_trade, routes_market,
                         routes_discovery, routes_decisions)
    app.include_router(routes_account.router)
    app.include_router(routes_trade.router)
    app.include_router(routes_market.router)
    app.include_router(routes_discovery.router)
    app.include_router(routes_decisions.router)
```

- [ ] **Step 5: Run test, expect pass; then full suite**

Run: `.venv/bin/python -m pytest tests/test_api_decisions.py -v && .venv/bin/python -m pytest -q`
Expected: target PASS; whole suite PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/routes_decisions.py backend/app/main.py backend/tests/test_api_decisions.py
git commit -m "feat(api): decisions list + approve(executes PaperBroker)/reject"
```

---

## Task 9: Config + run_decisions.py

**Files:**
- Modify: `backend/app/config.py`
- Create: `backend/scripts/run_decisions.py`
- Test: `backend/tests/test_config.py` (extend)

- [ ] **Step 1: Extend `backend/tests/test_config.py`**

Append this test:
```python
def test_decision_llm_defaults():
    s = Settings()
    assert s.decision_llm == "local"
    assert s.claude_bin.endswith("claude")
```

- [ ] **Step 2: Run test, expect failure**

Run: `.venv/bin/python -m pytest tests/test_config.py::test_decision_llm_defaults -v`
Expected: FAIL — attributes missing.

- [ ] **Step 3: Add fields to `backend/app/config.py`**

Add inside `class Settings` (after `initial_cash`):
```python
    decision_llm: str = "local"            # local | deepseek
    claude_bin: str = "/usr/local/bin/claude"
    debate_rounds: int = 2
```

- [ ] **Step 4: Run test, expect pass**

Run: `.venv/bin/python -m pytest tests/test_config.py -v`
Expected: PASS.

- [ ] **Step 5: Write `backend/scripts/run_decisions.py`**

```python
import sys
from pathlib import Path
from datetime import date

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings
from app.db.database import make_engine, make_session_factory, Base
import app.db.models  # noqa: F401
from app.db.models import Account, Position, DiscoveryPick
from sqlalchemy import select, func
from app.data.quote_store import QuoteStore
from app.decision.llm import LocalClaudeClient, DeepSeekClient
from app.decision.brief import build_brief
from app.decision.graph import DecisionGraph
from app.decision.runner import DecisionRunner


def _llm(s):
    if s.decision_llm == "deepseek":
        return DeepSeekClient(s.deepseek_api_key, s.deepseek_base_url, s.deepseek_model)
    return LocalClaudeClient(bin_path=s.claude_bin)


def main():
    s = get_settings()
    engine = make_engine(); Base.metadata.create_all(engine)
    session = make_session_factory(engine)()
    store = QuoteStore(session)

    as_of = store.trading_dates(date.today(), 1)[0]
    # targets = holdings ∪ latest discovery Top-8
    holds = {p.code: p for p in session.scalars(select(Position)).all()}
    top_date = session.scalar(select(func.max(DiscoveryPick.as_of)))
    top = [r.code for r in session.scalars(
        select(DiscoveryPick).where(DiscoveryPick.as_of == top_date)).all()] if top_date else []
    codes = sorted(set(holds) | set(top))

    briefs = []
    start = date(as_of.year - 1, as_of.month, as_of.day)
    for code in codes:
        bars = store.get_bars(code, start, as_of)
        closes = [b.close for b in bars][-20:]
        h = holds.get(code)
        holding = {"shares": h.shares, "cost": h.cost} if h else None
        briefs.append(build_brief(code, closes, {}, {}, holding))

    runner = DecisionRunner(session, DecisionGraph(_llm(s), rounds=s.debate_rounds))
    out = runner.run(as_of, briefs)
    for d in out:
        print(f"{d.code}  {d.action}  conf={d.confidence}  shares={d.shares}", flush=True)
    print(f"DECISIONS_DONE as_of={as_of} n={len(out)}", flush=True)


if __name__ == "__main__":
    main()
```

- [ ] **Step 6: Sanity check + commit**

Run (from `backend/`): `.venv/bin/python scripts/run_decisions.py --help 2>&1 | head -1 || .venv/bin/python -c "import ast; ast.parse(open('scripts/run_decisions.py').read()); print('parses')"`
Expected: `parses` (no argparse, so the import/parse check suffices).

```bash
git add backend/app/config.py backend/scripts/run_decisions.py backend/tests/test_config.py
git commit -m "feat(decision): config (decision_llm/claude_bin) + run_decisions runner script"
```

---

## Task 10: Frontend 决策 panel

**Files:**
- Create: `frontend/src/components/DecisionsPanel.tsx`
- Modify: `frontend/src/pages/Dashboard.tsx`

- [ ] **Step 1: Write `frontend/src/components/DecisionsPanel.tsx`**

```tsx
import { useCallback, useEffect, useState } from "react";
import { apiGet, apiPost } from "../api/client";

type Decision = { id: number; code: string; action: string; confidence: number;
  shares: number; status: string; reasoning: string };

export function DecisionsPanel() {
  const [rows, setRows] = useState<Decision[]>([]);
  const load = useCallback(() => {
    apiGet<Decision[]>("/api/decisions").then(setRows).catch(() => {});
  }, []);
  useEffect(load, [load]);

  async function act(id: number, what: "approve" | "reject") {
    const body = what === "approve" ? { price: 0 } : {};
    await apiPost(`/api/decisions/${id}/${what}`, body);
    load();
  }

  if (!rows.length) return <p>暂无决策</p>;
  return (
    <div style={{ display: "grid", gap: 12 }}>
      {rows.map((d) => (
        <div key={d.id} style={{ border: "1px solid #ccc", padding: 8 }}>
          <b>{d.code}</b> — {d.action} (信心 {d.confidence.toFixed(2)}, {d.shares}股)
          {" "}[{d.status}]
          {d.status === "PENDING" && (
            <span style={{ marginLeft: 8 }}>
              <button onClick={() => act(d.id, "approve")}>批准</button>
              <button onClick={() => act(d.id, "reject")}>驳回</button>
            </span>
          )}
          <details><summary>理由</summary>
            <pre style={{ whiteSpace: "pre-wrap" }}>{d.reasoning}</pre>
          </details>
        </div>
      ))}
    </div>
  );
}
```

- [ ] **Step 2: Add panel to `frontend/src/pages/Dashboard.tsx`**

Add import at top:
```tsx
import { DecisionsPanel } from "../components/DecisionsPanel";
```
After the discovery panel section, add:
```tsx
      <h2>决策(人机协同)</h2>
      <DecisionsPanel />
```

- [ ] **Step 3: Build to verify types**

Run: `cd frontend && npm run build`
Expected: build succeeds.

- [ ] **Step 4: Commit**

```bash
git add frontend/src -- ':!frontend/node_modules'
git commit -m "feat(frontend): 决策 panel with approve/reject + reasoning"
```

---

## Task 11: Integration + README

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Full backend suite**

Run (from `backend/`): `.venv/bin/python -m pytest -q`
Expected: all prior + new decision tests PASS.

- [ ] **Step 2: Real small-sample run (local Claude)**

Seed at least one holding/discovery pick, then:
```bash
cd backend && .venv/bin/python scripts/run_decisions.py
```
Expected: prints `<code> <action> conf=.. shares=..` lines and `DECISIONS_DONE`.
(Local Claude is slow; a 1–2 stock target is enough to validate end-to-end.)
Verify `GET /api/decisions` returns PENDING rows; the dashboard 决策 panel shows them.

- [ ] **Step 3: Add a "Decision engine" section to `README.md`**

```markdown
## Decision engine (multi-agent, slice 3)

Weekly multi-agent debate (量价/基本面 analysts → 多空 researchers → trader →
risk committee) over holdings ∪ discovery Top-8, producing BUY/SELL/HOLD with
reasoning. LLM is pluggable — default **local Claude** (`claude -p`), or DeepSeek
(`DECISION_LLM=deepseek`). Decisions are PENDING until approved in the UI, which
executes the PaperBroker.

```bash
cd backend
.venv/bin/python scripts/run_decisions.py     # default local Claude (slow)
DECISION_LLM=deepseek .venv/bin/python scripts/run_decisions.py
```

Surfaced at `GET /api/decisions`, `POST /api/decisions/{id}/approve|reject`, and the
dashboard 决策 panel. 研报/新闻 analyst is a stub until slice 4 wires scraped reports.
```

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "docs: README section for the multi-agent decision engine"
```

---

## Self-Review (completed by author)

**Spec coverage:**
- Pluggable LLMClient (LocalClaude default, DeepSeek) → Tasks 2, 3 ✓
- Ported agent roles + debate flow → Tasks 5, 6 ✓
- StockBrief from our data → Task 4 (assembly) + Task 9 (wires QuoteStore/discovery/holding) ✓
- JSON verdict + parse fallback → Task 2 `parse_verdict`, Task 6 HOLD default ✓
- decisions model + idempotent persist → Tasks 1, 7 ✓
- API list/approve(execute)/reject → Task 8 ✓
- Config (decision_llm/claude_bin) + weekly runner → Task 9 ✓
- 决策 panel approve/reject + reasoning → Task 10 ✓
- 研报/新闻 stub for slice 4 → Task 5 role present, fed empty ✓

**Placeholder scan:** none — every code step complete; Tasks 9/11 integration with
explicit commands; the news/research role is intentionally a stub (documented).

**Type consistency:** `LLMClient.complete(prompt, system)` consistent across impls,
agents, graph, fakes. `AgentReport(role, text, verdict)` consistent. `StockBrief`
fields (code, recent_closes, factors, fundamentals, holding) + `to_prompt()` consistent
across brief/graph/runner/tests. `Decision` (graph dataclass: action/confidence/shares/
reasoning) maps to the `Decision` model columns in the runner. `ROLES` keys referenced
in `DecisionGraph` all exist. API approve uses PaperBroker `buy/sell(account_id, code,
price, shares, on)` — matches slice-1 signature.

**Known risks (flagged):**
- Local Claude `claude -p` is serial + slow; full role set × N stocks is minutes-scale.
  Mitigate with small targets / `DECISION_LLM=deepseek`. Interface makes the swap trivial.
- approve uses a client-supplied `price` for the MVP; a later version reads latest close
  from QuoteStore server-side.
- A nested `claude -p` call runs a full Claude turn; the integration run should use a
  tiny target set to bound cost/time.
```
