# Phase 2: 每日定时编排 + 有界迭代 + 自动执行 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把"qlib 因子选股 → AI 辩论 → 自动纸面执行 → 盯市"接进 `daily_full` 每日链路,用有界迭代避免对全市场辩论,并给自动下单加置信度门与幂等保护。

**Architecture:** 新增纯逻辑 `select_debate_candidates`(有界迭代选候选)和编排 `run_daily_decisions`(选候选→建brief→辩论→执行→盯市→摘要),两者完全可注入、可单测。`DecisionRunner` 加 `min_confidence` 门;编排用"当日已决策代码"做 skip 实现幂等(防重复下单)。`daily_full.run_all` 链尾追加 step_select / step_debate / step_mark。调度沿用现有 APScheduler(`app/scheduler.py` + `enable_scheduler`)。

**Tech Stack:** Python 3.11, SQLAlchemy, pytest, APScheduler。复用 `app/discovery/qlib_provider.run_qlib_discovery`(Phase 1)、`app/decision/{graph,brief,runner}`、`app/trading/broker.PaperBroker`、`app/data/{quote_store,prices}`。

## Global Constraints

- Python 3.11;不新增第三方依赖。
- 现有 `DiscoveryPick` 在 qlib 源下是**全市场全量排序**(5000+ 行);任何"取最新日 DiscoveryPick 全部去辩论"的旧逻辑都不可直接用——必须经有界迭代。
- 默认参数(写进 `Settings`,实测后再调):`target_positions=15`、`quality_pctl=0.30`(候选复合分须在全市场前 30%)、`min_confidence=0.6`(BUY/SELL 自动执行的置信度门)、`max_debate=32`(单日辩论上限)、账户 `account_id=1`。
- 自动执行只动纸面 `PaperBroker`;BUY/SELL 仅在 `confidence ≥ min_confidence` 且 `shares>0` 且有最新价时执行,否则记录决策但不下单(`status="LOW_CONF"`)。
- 幂等:同一交易日重复跑 `run_all` 不重复辩论、不重复下单——编排把"当日已存在决策的代码"作为 skip 排除。
- 失败隔离:沿用 `run_all` 逐步 try/except;有数据依赖的步缺料则跳过+告警,不拿旧数据硬跑。
- DiscoveryPick.code / Position.code 一律规范格式 `600519.SH`(Phase 1 已保证 qlib 源输出规范格式)。
- 测试用 conftest 的 `session` fixture(in-memory sqlite);需账户时 `session.add(Account(id=1, name="main", cash=...))`;辩论一律注入 `FakeGraph`,不调真实 LLM。

---

### Task 1: 有界迭代选候选(纯逻辑)

**Files:**
- Create: `backend/app/decision/selection.py`
- Test: `backend/tests/test_selection.py`

**Interfaces:**
- Produces:
  - `select_debate_candidates(ranking: list[tuple[str, float]], held: set[str], *, target: int, quality_pctl: float, max_debate: int, skip: set[str] = frozenset()) -> list[str]`
  - 规则:① 先把当前持仓(`held`,减去 `skip`)放入辩论列表(持仓总要辩论以决定 HOLD/SELL),持仓即使不在 `ranking` 里也纳入;② 买入候选填空位 `slots = max(0, target - len(held))`,从 `ranking` 顶部按序取(排除 held/skip),停止条件任一:填满 slots / 候选排名位次 `i >= int(quality_pctl*len(ranking))`(跌出前 quality_pctl)/ ranking 取尽;③ 最终列表整体截断到 `max_debate`。

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_selection.py
from app.decision.selection import select_debate_candidates


def _ranking(n):
    # 降序排名:c0 最高 ... c{n-1} 最低
    return [(f"c{i}", float(n - i)) for i in range(n)]


def test_fills_slots_from_top_excluding_held():
    r = _ranking(100)
    out = select_debate_candidates(r, held=set(), target=3, quality_pctl=0.30, max_debate=32)
    assert out == ["c0", "c1", "c2"]          # 空仓→填满3个空位,取最强3只


def test_holdings_always_debated_and_consume_target():
    r = _ranking(100)
    out = select_debate_candidates(r, held={"c50"}, target=3, quality_pctl=0.30, max_debate=32)
    # 持仓 c50 必辩;空位=3-1=2,买入候选取 c0,c1
    assert out[0] == "c50"
    assert set(out) == {"c50", "c0", "c1"}


def test_quality_floor_stops_buys():
    r = _ranking(10)                          # 前30% = 前3名(index 0,1,2)
    out = select_debate_candidates(r, held=set(), target=8, quality_pctl=0.30, max_debate=32)
    assert out == ["c0", "c1", "c2"]          # 想填8个,但只有前3只过质量门


def test_skip_excludes_already_decided():
    r = _ranking(100)
    out = select_debate_candidates(r, held={"c50"}, target=3, quality_pctl=0.30,
                                   max_debate=32, skip={"c50", "c0"})
    # c50 被 skip 不辩;c0 被 skip 跳过;空位=3-1=2 → c1,c2
    assert "c50" not in out and "c0" not in out
    assert out == ["c1", "c2"]


def test_max_debate_caps_total():
    r = _ranking(100)
    out = select_debate_candidates(r, held=set(), target=50, quality_pctl=1.0, max_debate=5)
    assert len(out) == 5


def test_held_not_in_ranking_still_debated():
    r = _ranking(10)
    out = select_debate_candidates(r, held={"DELISTED.SH"}, target=1, quality_pctl=0.30,
                                   max_debate=32)
    assert "DELISTED.SH" in out               # 持仓不在排名里也要辩(可能要卖)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/pytest tests/test_selection.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.decision.selection'`

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/decision/selection.py
"""有界迭代选候选:持仓必辩,买入候选按复合分排名填空位,卡质量门与单日上限。
不强迫交易——空仓合法,候选不够好就少辩甚至不买。"""


def select_debate_candidates(ranking: list[tuple[str, float]], held: set[str], *,
                             target: int, quality_pctl: float, max_debate: int,
                             skip: set[str] = frozenset()) -> list[str]:
    held = set(held)
    skip = set(skip)
    in_ranking = {c for c, _ in ranking}
    debate: list[str] = []
    # ① 持仓必辩(减去 skip);先排名内的,再排名外的(可能已退市但仍持有)
    for code, _ in ranking:
        if code in held and code not in skip:
            debate.append(code)
    for code in held:
        if code not in in_ranking and code not in skip:
            debate.append(code)
    # ② 买入候选填空位,卡质量门
    slots = max(0, target - len(held))
    floor_idx = int(quality_pctl * len(ranking))
    for i, (code, _) in enumerate(ranking):
        if slots <= 0 or i >= floor_idx:
            break
        if code in held or code in skip:
            continue
        debate.append(code)
        slots -= 1
    # ③ 整体截断
    return debate[:max_debate]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/bin/pytest tests/test_selection.py -v`
Expected: PASS (6 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/app/decision/selection.py backend/tests/test_selection.py
git commit -m "feat(decision): bounded-iteration debate candidate selection"
```

---

### Task 2: DecisionRunner 加置信度门

**Files:**
- Modify: `backend/app/decision/runner.py`
- Test: `backend/tests/test_decision_runner_confidence.py`

**Interfaces:**
- Consumes: 现有 `DecisionRunner.__init__(session, graph, broker=None, account_id=1, price_of=None)`、`PaperBroker`、`Decision` 模型。
- Produces:
  - `DecisionRunner.__init__` 新增关键字参数 `min_confidence: float = 0.0`(默认 0.0 保持现有行为/测试不变)。
  - 自动执行规则改为:`broker` 存在且 `d.action in ("BUY","SELL")` 且 `d.shares>0`:
    - `d.confidence < min_confidence` → 不下单,`status="LOW_CONF"`,reasoning 追加 `\n\n⚠️ 置信度 {conf} < {min_confidence},跳过自动执行`
    - 否则按原逻辑下单(有最新价),`status="APPROVED"`
  - HOLD 或 shares==0:`status="APPROVED"`,不下单(不变)。无 broker:`status="PENDING"`(不变)。

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_decision_runner_confidence.py
from datetime import date
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.db.database import Base
import app.db.models  # noqa
from app.db.models import Account
from app.decision.runner import DecisionRunner
from app.decision.brief import build_brief
from app.trading.broker import PaperBroker


class _Dec:
    def __init__(self, action, shares, confidence):
        self.action = action; self.shares = shares
        self.confidence = confidence; self.reasoning = "### 风控经理\n裁决"


class _Graph:
    def __init__(self, dec): self._d = dec
    def run(self, brief): return self._d


def _sess():
    e = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                      poolclass=StaticPool, future=True)
    Base.metadata.create_all(e)
    s = sessionmaker(bind=e, future=True)()
    s.add(Account(id=1, name="main", cash=1_000_000.0)); s.commit()
    return s


def test_below_threshold_records_lowconf_no_trade():
    s = _sess()
    runner = DecisionRunner(s, _Graph(_Dec("BUY", 100, 0.5)), broker=PaperBroker(s),
                            account_id=1, price_of=lambda c: 100.0, min_confidence=0.6)
    out = runner.run(date(2026, 6, 4), [build_brief("600519.SH", [100], {}, {}, None)])
    assert out[0].status == "LOW_CONF"
    assert s.get(Account, 1).cash == 1_000_000.0          # 没扣钱=没下单


def test_at_or_above_threshold_executes():
    s = _sess()
    runner = DecisionRunner(s, _Graph(_Dec("BUY", 100, 0.6)), broker=PaperBroker(s),
                            account_id=1, price_of=lambda c: 100.0, min_confidence=0.6)
    out = runner.run(date(2026, 6, 4), [build_brief("600519.SH", [100], {}, {}, None)])
    assert out[0].status == "APPROVED"
    assert s.get(Account, 1).cash == 1_000_000.0 - 100.0 * 100
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/pytest tests/test_decision_runner_confidence.py -v`
Expected: FAIL — `TypeError: __init__() got an unexpected keyword argument 'min_confidence'`

- [ ] **Step 3: Write minimal implementation**

Modify `backend/app/decision/runner.py`. Change `__init__` to accept `min_confidence` and the execution block to gate on it:

```python
    def __init__(self, session: Session, graph: DecisionGraph,
                 broker: Optional[PaperBroker] = None, account_id: int = 1,
                 price_of: Optional[Callable[[str], Optional[float]]] = None,
                 min_confidence: float = 0.0):
        self.s = session
        self.graph = graph
        self.broker = broker
        self.account_id = account_id
        self.price_of = price_of
        self.min_confidence = min_confidence
```

Replace the body of the `if self.broker is not None:` block in `run` with:

```python
            if self.broker is not None:
                status = "APPROVED"
                if d.action in ("BUY", "SELL") and d.shares > 0:
                    if d.confidence < self.min_confidence:
                        status = "LOW_CONF"
                        reasoning += (f"\n\n⚠️ 置信度 {d.confidence} < "
                                      f"{self.min_confidence},跳过自动执行")
                    else:
                        price = self.price_of(brief.code) if self.price_of else None
                        if price:
                            try:
                                if d.action == "BUY":
                                    self.broker.buy(self.account_id, brief.code, price, d.shares, as_of)
                                else:
                                    self.broker.sell(self.account_id, brief.code, price, d.shares, as_of)
                            except (InsufficientFunds, InsufficientShares) as e:
                                reasoning += f"\n\n⚠️ 自动执行失败:{e}"
                        else:
                            reasoning += "\n\n⚠️ 自动执行跳过:无最新价"
```

- [ ] **Step 4: Run tests to verify they pass (new + existing autoexec unchanged)**

Run: `cd backend && .venv/bin/pytest tests/test_decision_runner_confidence.py tests/test_decision_autoexec.py tests/test_decision_runner.py -v`
Expected: PASS (existing autoexec/runner tests still green — default `min_confidence=0.0` preserves behavior)

- [ ] **Step 5: Commit**

```bash
git add backend/app/decision/runner.py backend/tests/test_decision_runner_confidence.py
git commit -m "feat(decision): confidence gate on auto-execution (LOW_CONF below threshold)"
```

---

### Task 3: 每日决策编排(选→辩→执行→摘要,幂等)

**Files:**
- Create: `backend/app/decision/daily_pipeline.py`
- Test: `backend/tests/test_daily_pipeline.py`

**Interfaces:**
- Consumes: Task 1 `select_debate_candidates`、Task 2 `DecisionRunner(..., min_confidence=)`、`Decision` 模型、`StockBrief`。
- Produces:
  - `today_decided_codes(session, as_of) -> set[str]` — 当日已存在决策的代码集合(幂等用)。
  - `run_daily_decisions(session, as_of, ranking, held_codes, *, graph, brief_builder, broker, price_of, target, quality_pctl, min_confidence, max_debate, account_id=1) -> dict` — 编排:`skip=today_decided_codes`;`select_debate_candidates(...)` 选候选;`briefs = brief_builder(candidates)`;`DecisionRunner(session, graph, broker, account_id, price_of, min_confidence).run(as_of, briefs)`;返回 `{"candidates": [...], "n_debated": int, "n_buy": int, "n_sell": int, "n_hold": int, "n_lowconf": int}`。`brief_builder: Callable[[list[str]], list[StockBrief]]` 可注入。

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_daily_pipeline.py
from datetime import date
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.db.database import Base
import app.db.models  # noqa
from app.db.models import Account, Decision
from app.decision.brief import build_brief
from app.trading.broker import PaperBroker
from app.decision.daily_pipeline import run_daily_decisions, today_decided_codes


class _Dec:
    def __init__(self, action, shares=100, confidence=0.8):
        self.action = action; self.shares = shares
        self.confidence = confidence; self.reasoning = "### 风控经理\n裁决"


class _Graph:
    """按代码尾号决定动作:默认全 BUY。"""
    def __init__(self, mapping=None): self._m = mapping or {}
    def run(self, brief):
        return self._m.get(brief.code, _Dec("BUY"))


def _sess():
    e = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                      poolclass=StaticPool, future=True)
    Base.metadata.create_all(e)
    s = sessionmaker(bind=e, future=True)()
    s.add(Account(id=1, name="main", cash=1_000_000.0)); s.commit()
    return s


def _bb(codes):
    return [build_brief(c, [100.0, 101.0], {}, {}, None) for c in codes]


def _ranking(n):
    return [(f"c{i}", float(n - i)) for i in range(n)]


def test_pipeline_debates_bounded_and_executes_buys():
    s = _sess()
    summary = run_daily_decisions(
        s, date(2026, 6, 4), _ranking(100), held_codes=set(),
        graph=_Graph(), brief_builder=_bb, broker=PaperBroker(s),
        price_of=lambda c: 100.0, target=3, quality_pctl=0.30, min_confidence=0.6,
        max_debate=32)
    assert summary["n_debated"] == 3              # 空仓填3个空位
    assert summary["n_buy"] == 3
    assert s.query(Decision).count() == 3
    assert s.get(Account, 1).cash == 1_000_000.0 - 3 * 100.0 * 100


def test_pipeline_idempotent_skips_already_decided():
    s = _sess()
    kw = dict(graph=_Graph(), brief_builder=_bb, broker=PaperBroker(s),
              price_of=lambda c: 100.0, target=3, quality_pctl=0.30,
              min_confidence=0.6, max_debate=32)
    run_daily_decisions(s, date(2026, 6, 4), _ranking(100), set(), **kw)
    cash_after_first = s.get(Account, 1).cash
    run_daily_decisions(s, date(2026, 6, 4), _ranking(100), set(), **kw)
    assert s.query(Decision).count() == 3          # 不新增决策
    assert s.get(Account, 1).cash == cash_after_first   # 不重复下单


def test_today_decided_codes():
    s = _sess()
    s.add(Decision(as_of=date(2026, 6, 4), code="600519.SH", action="BUY",
                   confidence=0.8, shares=100, reasoning="", status="APPROVED",
                   created_at=date(2026, 6, 4)))
    s.commit()
    assert today_decided_codes(s, date(2026, 6, 4)) == {"600519.SH"}
    assert today_decided_codes(s, date(2026, 6, 5)) == set()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/pytest tests/test_daily_pipeline.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.decision.daily_pipeline'`

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/decision/daily_pipeline.py
"""每日决策编排:有界迭代选候选 → 建 brief → 辩论 → 自动执行 → 返回摘要。
幂等:当日已决策的代码不重复辩论/下单。所有外部依赖(graph/brief_builder/broker)可注入。"""
from datetime import date
from typing import Callable, Optional
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.db.models import Decision
from app.decision.brief import StockBrief
from app.decision.graph import DecisionGraph
from app.decision.runner import DecisionRunner
from app.decision.selection import select_debate_candidates
from app.trading.broker import PaperBroker


def today_decided_codes(session: Session, as_of: date) -> set[str]:
    rows = session.scalars(select(Decision.code).where(Decision.as_of == as_of)).all()
    return set(rows)


def run_daily_decisions(session: Session, as_of: date,
                        ranking: list[tuple[str, float]], held_codes: set[str], *,
                        graph: DecisionGraph,
                        brief_builder: Callable[[list[str]], list[StockBrief]],
                        broker: Optional[PaperBroker], price_of, target: int,
                        quality_pctl: float, min_confidence: float, max_debate: int,
                        account_id: int = 1) -> dict:
    skip = today_decided_codes(session, as_of)
    candidates = select_debate_candidates(
        ranking, set(held_codes), target=target, quality_pctl=quality_pctl,
        max_debate=max_debate, skip=skip)
    briefs = brief_builder(candidates)
    runner = DecisionRunner(session, graph, broker=broker, account_id=account_id,
                            price_of=price_of, min_confidence=min_confidence)
    decisions = runner.run(as_of, briefs)
    n_buy = sum(1 for d in decisions if d.action == "BUY" and d.status == "APPROVED")
    n_sell = sum(1 for d in decisions if d.action == "SELL" and d.status == "APPROVED")
    n_hold = sum(1 for d in decisions if d.action == "HOLD")
    n_lowconf = sum(1 for d in decisions if d.status == "LOW_CONF")
    return {"candidates": candidates, "n_debated": len(decisions),
            "n_buy": n_buy, "n_sell": n_sell, "n_hold": n_hold, "n_lowconf": n_lowconf}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/bin/pytest tests/test_daily_pipeline.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/app/decision/daily_pipeline.py backend/tests/test_daily_pipeline.py
git commit -m "feat(decision): daily decision pipeline (bounded select + idempotent execute)"
```

---

### Task 4: 每日摘要构建

**Files:**
- Create: `backend/app/reporting/__init__.py`
- Create: `backend/app/reporting/daily_summary.py`
- Test: `backend/tests/test_daily_summary.py`

**Interfaces:**
- Consumes: `Account`、`Position`、`Trade`、`EquitySnapshot` 模型。
- Produces:
  - `build_daily_summary(session, as_of: date, account_id: int = 1) -> str` — 生成当日纯文本摘要(不含 markdown 表格,遵守 weixin 渠道纪律):当日买/卖笔数与代码、持仓数、现金/市值/总权益、对历史峰值的回撤。无 EquitySnapshot 时回撤显示 N/A。

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_daily_summary.py
from datetime import date
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.db.database import Base
import app.db.models  # noqa
from app.db.models import Account, Trade, EquitySnapshot
from app.reporting.daily_summary import build_daily_summary


def _sess():
    e = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                      poolclass=StaticPool, future=True)
    Base.metadata.create_all(e)
    s = sessionmaker(bind=e, future=True)()
    s.add(Account(id=1, name="main", cash=500_000.0)); s.commit()
    return s


def test_summary_lists_today_trades_and_drawdown():
    s = _sess()
    d = date(2026, 6, 4)
    s.add(Trade(account_id=1, code="600519.SH", side="BUY", price=100, shares=100, traded_at=d))
    s.add(EquitySnapshot(account_id=1, as_of=date(2026, 6, 1), cash=0, market_value=0, total=1_200_000.0))
    s.add(EquitySnapshot(account_id=1, as_of=d, cash=500_000.0, market_value=520_000.0, total=1_020_000.0))
    s.commit()
    text = build_daily_summary(s, d, account_id=1)
    assert "600519.SH" in text
    assert "买" in text
    # 峰值 1_200_000 → 当前 1_020_000,回撤 -15%
    assert "-15" in text
    assert "|" not in text and "---" not in text       # 不含 markdown 表格


def test_summary_handles_no_snapshot():
    s = _sess()
    text = build_daily_summary(s, date(2026, 6, 4), account_id=1)
    assert "N/A" in text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/pytest tests/test_daily_summary.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.reporting'`

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/reporting/__init__.py
```

```python
# backend/app/reporting/daily_summary.py
"""当日纯文本摘要(供 weixin 日报)。不用 markdown 表格,短句陈述。"""
from datetime import date
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.db.models import Account, Position, Trade, EquitySnapshot


def build_daily_summary(session: Session, as_of: date, account_id: int = 1) -> str:
    trades = session.scalars(select(Trade).where(
        Trade.account_id == account_id, Trade.traded_at == as_of)).all()
    buys = [t for t in trades if t.side == "BUY"]
    sells = [t for t in trades if t.side == "SELL"]
    positions = session.scalars(select(Position).where(
        Position.account_id == account_id)).all()
    acc = session.get(Account, account_id)
    snaps = session.scalars(select(EquitySnapshot).where(
        EquitySnapshot.account_id == account_id).order_by(EquitySnapshot.as_of)).all()

    lines = [f"📊 {as_of} 交易日报"]
    if buys:
        lines.append("买入:" + " ".join(f"{t.code}×{t.shares}" for t in buys))
    if sells:
        lines.append("卖出:" + " ".join(f"{t.code}×{t.shares}" for t in sells))
    if not buys and not sells:
        lines.append("今日无成交")
    lines.append(f"持仓 {len(positions)} 只")
    if snaps:
        cur = snaps[-1]
        peak = max(x.total for x in snaps)
        dd = (cur.total / peak - 1.0) if peak else 0.0
        lines.append(f"现金 {acc.cash:.0f} / 市值 {cur.market_value:.0f} / "
                     f"总权益 {cur.total:.0f}")
        lines.append(f"回撤 {dd*100:.1f}%")
    else:
        lines.append(f"现金 {acc.cash:.0f} / 权益快照 N/A / 回撤 N/A")
    return "\n".join(lines)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/bin/pytest tests/test_daily_summary.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/app/reporting/__init__.py backend/app/reporting/daily_summary.py backend/tests/test_daily_summary.py
git commit -m "feat(reporting): plain-text daily summary (trades/equity/drawdown)"
```

---

### Task 5: Settings 配置项

**Files:**
- Modify: `backend/app/config.py`
- Test: `backend/tests/test_config_phase2.py`

**Interfaces:**
- Produces: `Settings` 新增字段 `target_positions: int = 15`、`quality_pctl: float = 0.30`、`min_confidence: float = 0.6`、`max_debate: int = 32`。

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_config_phase2.py
from app.config import Settings


def test_phase2_defaults():
    s = Settings()
    assert s.target_positions == 15
    assert s.quality_pctl == 0.30
    assert s.min_confidence == 0.6
    assert s.max_debate == 32
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/pytest tests/test_config_phase2.py -v`
Expected: FAIL with `AttributeError: 'Settings' object has no attribute 'target_positions'`

- [ ] **Step 3: Write minimal implementation**

Add to the `Settings` class in `backend/app/config.py` (after `daily_update_minute`):

```python
    target_positions: int = 15             # 组合目标持仓数(空位上界)
    quality_pctl: float = 0.30             # 买入候选须在全市场复合分前 30%
    min_confidence: float = 0.6            # BUY/SELL 自动执行的置信度门
    max_debate: int = 32                   # 单日辩论上限(防烧 LLM)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/bin/pytest tests/test_config_phase2.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/config.py backend/tests/test_config_phase2.py
git commit -m "feat(config): phase2 knobs (target/quality/min_confidence/max_debate)"
```

---

### Task 6: 接入 daily_full(step_select / step_debate / step_mark)

**Files:**
- Modify: `backend/scripts/daily_full.py`
- Test: `backend/tests/test_daily_full_phase2.py`

**Interfaces:**
- Consumes: Phase 1 `app/discovery/qlib_provider.run_qlib_discovery`、`app/factors/frozen.load_frozen`、`scripts/freeze_factors.frozen_path`、`app/backtest/qlib_data.init_qlib`;Task 3 `run_daily_decisions`;Task 4 `build_daily_summary`;`PaperBroker`、`MapPriceProvider`、`latest_close`、`DecisionGraph`、`build_brief`、`QuoteStore`、`Position`、`DiscoveryPick`。
- Produces: `daily_full` 新增模块级 `step_select()`、`step_debate()`、`step_mark()`;`run_all()` 的步骤元组扩展为 `(step_quotes, step_qlib, step_tracklist, step_select, step_debate, step_mark)`,保持逐步失败隔离;`step_debate` 末尾 `print(build_daily_summary(...))`(日志即日报内容,weixin 投递由运维层接管)。

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_daily_full_phase2.py
import scripts.daily_full as df


def test_run_all_includes_phase2_steps_in_order(monkeypatch):
    calls = []
    for name in ("step_quotes", "step_qlib", "step_tracklist",
                 "step_select", "step_debate", "step_mark"):
        monkeypatch.setattr(df, name, (lambda n=name: lambda: calls.append(n))())
    df.run_all()
    assert calls == ["quotes", "qlib", "track", "select", "debate", "mark"] or \
           calls == ["step_quotes", "step_qlib", "step_tracklist",
                     "step_select", "step_debate", "step_mark"]


def test_run_all_isolates_phase2_step_failure(monkeypatch):
    calls = []
    monkeypatch.setattr(df, "step_quotes", lambda: calls.append("step_quotes"))
    monkeypatch.setattr(df, "step_qlib", lambda: calls.append("step_qlib"))
    monkeypatch.setattr(df, "step_tracklist", lambda: calls.append("step_tracklist"))

    def boom(): raise RuntimeError("select failed")
    monkeypatch.setattr(df, "step_select", boom)
    monkeypatch.setattr(df, "step_debate", lambda: calls.append("step_debate"))
    monkeypatch.setattr(df, "step_mark", lambda: calls.append("step_mark"))
    ok = df.run_all()
    assert "step_debate" in calls and "step_mark" in calls    # 后续步不被阻断
    assert ok is False
```

注:第一个测试两种期望写法是因为实现可用任意 append 标签;实现时让每个 step append 一个稳定标签(下方实现用方法名短标签 `"quotes"/"qlib"/"track"/"select"/"debate"/"mark"`,故第一分支成立)。

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/pytest tests/test_daily_full_phase2.py -v`
Expected: FAIL with `AttributeError: module 'scripts.daily_full' has no attribute 'step_select'`

- [ ] **Step 3: Write minimal implementation**

In `backend/scripts/daily_full.py`, add imports near the top (after existing imports):

```python
from sqlalchemy import select, func
from app.db.models import Position, DiscoveryPick
from app.data.prices import DictPriceProvider, latest_close
from app.trading.broker import PaperBroker
from app.decision.graph import DecisionGraph
from app.decision.brief import build_brief
from app.decision.llm import LocalClaudeClient, DeepSeekClient
from app.decision.daily_pipeline import run_daily_decisions
from app.reporting.daily_summary import build_daily_summary
```

Add the three step functions (before `run_all`):

```python
def _llm(s):
    if s.decision_llm == "deepseek":
        return DeepSeekClient(s.deepseek_api_key, s.deepseek_base_url, s.deepseek_model)
    return LocalClaudeClient(bin_path=s.claude_bin)


def _session():
    return make_session_factory(make_engine())()


def step_select() -> None:
    from app.backtest.qlib_data import init_qlib
    from app.factors.frozen import load_frozen
    from app.discovery.qlib_provider import run_qlib_discovery
    from scripts.freeze_factors import frozen_path
    s = get_settings()
    session = _session()
    store = QuoteStore(session)
    as_of = store.trading_dates(date.today(), 1)[0]
    init_qlib(s.qlib_data_dir)
    from qlib.data import D
    frozen = load_frozen(frozen_path(s))
    insts = D.list_instruments(D.instruments(frozen.universe), as_list=True)
    run_qlib_discovery(session, as_of, frozen, insts)


def step_debate() -> None:
    s = get_settings()
    session = _session()
    store = QuoteStore(session)
    as_of = store.trading_dates(date.today(), 1)[0]
    top_date = session.scalar(select(func.max(DiscoveryPick.as_of)))
    ranking = [(r.code, r.score) for r in session.scalars(
        select(DiscoveryPick).where(DiscoveryPick.as_of == top_date)
        .order_by(DiscoveryPick.rank)).all()] if top_date else []
    if not ranking:
        raise RuntimeError("step_debate: 无 DiscoveryPick 产物,跳过(先跑 step_select)")
    held = {p.code for p in session.scalars(
        select(Position).where(Position.account_id == 1)).all()}

    def brief_builder(codes):
        start = date(as_of.year - 1, as_of.month, as_of.day)
        out = []
        for code in codes:
            bars = store.get_bars(code, start, as_of)
            closes = [b.close for b in bars][-20:]
            out.append(build_brief(code, closes, {}, {}, None))
        return out

    summary = run_daily_decisions(
        session, as_of, ranking, held, graph=DecisionGraph(_llm(s), rounds=s.debate_rounds),
        brief_builder=brief_builder, broker=PaperBroker(session),
        price_of=lambda c: latest_close(store, c, as_of),
        target=s.target_positions, quality_pctl=s.quality_pctl,
        min_confidence=s.min_confidence, max_debate=s.max_debate, account_id=1)
    print(build_daily_summary(session, as_of, account_id=1), flush=True)
    print(f"DEBATE_DONE {summary}", flush=True)


def step_mark() -> None:
    session = _session()
    store = QuoteStore(session)
    as_of = store.trading_dates(date.today(), 1)[0]
    held = session.scalars(select(Position).where(Position.account_id == 1)).all()
    prices = DictPriceProvider({p.code: (latest_close(store, p.code, as_of) or 0.0)
                               for p in held})
    PaperBroker(session).mark_to_market(1, prices, as_of)
```

Update `run_all` step tuple:

```python
    for step in (step_quotes, step_qlib, step_tracklist,
                 step_select, step_debate, step_mark):
```

(Each existing step already appends nothing; the test monkeypatches them. Keep the existing `step_quotes/step_qlib/step_tracklist` bodies unchanged.)

Note on `DictPriceProvider`: this is the confirmed concrete `PriceProvider` in `app/data/prices.py` wrapping a `dict[str, float]`; its `latest_close(code)` does `self._prices[code]` (raises KeyError on a missing code). `step_mark` builds the dict from exactly the held positions, so every code mark_to_market queries is present.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/bin/pytest tests/test_daily_full_phase2.py tests/test_daily_full.py -v`
Expected: PASS (both the new phase2 order/isolation tests and the original daily_full tests)

- [ ] **Step 5: Commit**

```bash
git add backend/scripts/daily_full.py backend/tests/test_daily_full_phase2.py
git commit -m "feat(daily): wire qlib select + bounded debate + mark-to-market into run_all"
```

---

### Task 7: 全链冒烟(集成,真实 qlib + LLM 可跳过)

**Files:**
- Test: `backend/tests/test_daily_full_integration.py`

**Interfaces:**
- Consumes: `scripts.daily_full.step_select`、`DiscoveryPick`。

- [ ] **Step 1: Write the integration test**

只验证最重的、不依赖 LLM 的一步(step_select 真实写出 DiscoveryPick);辩论步依赖 LLM,集成冒烟由手动执行覆盖,不进自动测试。

```python
# backend/tests/test_daily_full_integration.py
from pathlib import Path
import pytest
from app.config import get_settings

pytestmark = pytest.mark.integration


def _has_qlib_and_frozen() -> bool:
    s = get_settings()
    from scripts.freeze_factors import frozen_path
    return Path(s.qlib_data_dir, "calendars").exists() and frozen_path(s).exists()


@pytest.mark.skipif(not _has_qlib_and_frozen(), reason="需 qlib 数据 + frozen 产物")
def test_step_select_writes_discovery_picks():
    import scripts.daily_full as df
    from app.db.database import make_engine, make_session_factory
    from sqlalchemy import select, func
    from app.db.models import DiscoveryPick
    df.step_select()
    session = make_session_factory(make_engine())()
    n = session.scalar(select(func.count()).select_from(DiscoveryPick))
    assert n and n > 100        # 全市场全量写入
```

- [ ] **Step 2: Run integration test**

Run: `cd backend && .venv/bin/pytest tests/test_daily_full_integration.py -v -m integration`
Expected: PASS(本地有 qlib 数据 + frozen 产物时);否则 SKIP

- [ ] **Step 3: Manual full-chain smoke + commit**

```bash
# 手动跑一次全链(会真实调用 LLM 辩论,耗时;确认无异常即可)
cd backend && .venv/bin/python scripts/daily_full.py
# 预期日志出现 DISCOVERY、DEBATE_DONE {...}、日报文本、并写出 EquitySnapshot
git add backend/tests/test_daily_full_integration.py
git commit -m "test(daily): step_select integration writes discovery picks"
```

---

## Self-Review

**Spec coverage(对照 spec §6 Phase 2):**
- §6.1 有界迭代(空位=target−持仓、批/质量门/取尽停止、不强买)→ Task 1 `select_debate_candidates` + Task 3 编排 ✓
- §6.2 自动执行(置信度≥0.6 自动纸面下单,无人工关口)→ Task 2 置信度门 + Task 3 编排走 broker ✓
- §6.3 失败隔离 + 幂等(同日重复跑不重复下单)→ Task 6 run_all 逐步隔离 + Task 3 skip 已决策代码 ✓
- §6.4 调度(收盘触发 run_all)→ 沿用现有 `app/scheduler.py`+`enable_scheduler`(无需改;时间由 `daily_update_hour/minute` 配置)✓
- §6.5 验收(手动跑全链到 EquitySnapshot;重复跑不重复)→ Task 6 + Task 7 手动冒烟 ✓
- 日报(买/卖/持/权益/回撤,不用 markdown 表格)→ Task 4 `build_daily_summary` ✓
- "现 DiscoveryPick 全量 5000+ 不能整体辩论" → Task 1 有界迭代是 correctness 必需,已覆盖 ✓

**Placeholder scan:** 无 TBD/TODO;每代码步含完整代码与预期输出。已核实 `DictPriceProvider`(prices.py 真实类名)、`DiscoveryPick.score: Float`、`DiscoveryPick.rank: Integer`。

**Type consistency:**
- `select_debate_candidates(ranking, held, *, target, quality_pctl, max_debate, skip)` Task 1 定义,Task 3 调用一致。
- `DecisionRunner(..., min_confidence=)` Task 2 定义,Task 3 使用一致。
- `run_daily_decisions(session, as_of, ranking, held_codes, *, graph, brief_builder, broker, price_of, target, quality_pctl, min_confidence, max_debate, account_id)` Task 3 定义,Task 6 调用一致。
- `build_daily_summary(session, as_of, account_id)` Task 4 定义,Task 6 调用一致。
- `Settings` 字段名(target_positions/quality_pctl/min_confidence/max_debate)Task 5 定义,Task 6 通过 `s.<field>` 引用一致。

**执行前需核对的真实接口(给实现者):**
1. `DictPriceProvider`、`DiscoveryPick.score: Float`、`DiscoveryPick.rank: Integer` 已核实(rank 升序=分数降序,Phase 1 写入保证;Task 6 `order_by(DiscoveryPick.rank)` 即得降序排名)。
2. 账户 `id=1` 已 seed(`scripts/seed_account.py`);生产环境跑前确保已 seed,否则 `step_debate`/`step_mark` 取不到 Account——这类异常由 run_all 逐步 try/except 隔离,不阻断其他步。
