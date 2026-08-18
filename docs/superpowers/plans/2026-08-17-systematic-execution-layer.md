# 系统化执行层(TopkDropout + 辩论否决)实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把夜链执行从"逐股辩论+0.6置信度门槛"换成"系统按因子分选前15、周度等权满仓轮动(TopkDropout),辩论只做 SELL 否决"。

**Architecture:** 新增 `app/portfolio/` 两个模块——`rebalance.py`(纯函数:再平衡日判定、买卖清单、等权定股数)与 `execute.py`(编排:plan→辩论否决→先卖后买→落 Decision,依赖全注入可测)。`daily_full.step_debate` 改写为薄壳 `step_rebalance` 调用编排;`DecisionRunner` 的 0.6 门槛退出夜链路径。

**Tech Stack:** Python 3.11、SQLAlchemy、pytest。纸面账户 `PaperBroker`,无真钱。

## Global Constraints

- 组合口径复制回测:持有因子分最高 `topk=15` 只创业板股、等权(每只目标市值=总权益/15)、满仓。
- 轮动:每周 `rebalance_weekday=0`(周一)一次;其余交易日 step 直接跳过不动。
- TopkDropout 缓冲:持仓 `rank > topk + buffer`(buffer=5,即跌出第20名)才卖。
- 辩论=否决层:仅 `action == "SELL"` 否决(待买跳过取后备、持仓清仓);HOLD/BUY/低置信度不拦。0.6 门槛在夜链下线。
- 先卖后买(释放现金再买)。下单失败(资金/持股不足)fail-soft,记 reasoning 不崩。
- A股整手 `lot=100`。
- TDD;后端测试命令:`cd backend && .venv/bin/python -m pytest <file> -q`。

---

### Task 1: 纯函数模块 `app/portfolio/rebalance.py`

**Files:**
- Create: `backend/app/portfolio/__init__.py`(空文件)
- Create: `backend/app/portfolio/rebalance.py`
- Test: `backend/tests/test_portfolio_rebalance.py`

**Interfaces:**
- Produces:
  - `is_rebalance_day(as_of: date, weekday: int) -> bool`
  - `plan_rebalance(ranked: list[tuple[str, int]], held: set[str], *, topk: int, buffer: int) -> tuple[list[str], list[str]]` — 返回 `(sells, buy_candidates)`,均为排序后的 list[str]。
  - `equal_weight_shares(equity: float, topk: int, price: float, lot: int = 100) -> int`

- [ ] **Step 1: 写失败测试**

新建 `backend/tests/test_portfolio_rebalance.py`:

```python
from datetime import date
from app.portfolio.rebalance import (
    is_rebalance_day, plan_rebalance, equal_weight_shares)


def test_is_rebalance_day():
    assert is_rebalance_day(date(2026, 8, 17), 0) is True    # 周一
    assert is_rebalance_day(date(2026, 8, 18), 0) is False   # 周二
    assert is_rebalance_day(date(2026, 8, 18), 1) is True    # 配周二


def _ranked(n):
    return [(f"3000{i:02d}.SZ", i + 1) for i in range(n)]     # rank 从 1


def test_plan_empty_holdings_buys_topk_plus_buffer_candidates():
    sells, buys = plan_rebalance(_ranked(30), set(), topk=15, buffer=5)
    assert sells == []
    # 空位=15,候选给 slots+buffer=20 个,按 rank 升序
    assert buys == [f"3000{i:02d}.SZ" for i in range(20)]


def test_plan_all_held_in_topk_no_action():
    held = {f"3000{i:02d}.SZ" for i in range(15)}
    sells, buys = plan_rebalance(_ranked(30), held, topk=15, buffer=5)
    assert sells == []
    assert buys == []                                        # 无空位


def test_plan_holding_dropped_out_of_buffer_is_sold_and_refilled():
    # 持仓 300021(rank 22 > 15+5)应卖;空出 1 位,买 rank 最高的未持仓
    held = {f"3000{i:02d}.SZ" for i in range(14)} | {"300021.SZ"}
    sells, buys = plan_rebalance(_ranked(30), held, topk=15, buffer=5)
    assert sells == ["300021.SZ"]
    assert buys[0] == "300014.SZ"                            # rank15,第一个未持仓
    assert len(buys) == 1 + 5                                # slots=1 +buffer


def test_plan_holding_within_buffer_not_sold():
    held = {"300017.SZ"}                                     # rank 18,在 15+5 内
    sells, buys = plan_rebalance(_ranked(30), held, topk=15, buffer=5)
    assert "300017.SZ" not in sells


def test_plan_delisted_holding_sold():
    held = {"999999.SZ"}                                     # 不在 ranked
    sells, buys = plan_rebalance(_ranked(30), held, topk=15, buffer=5)
    assert sells == ["999999.SZ"]


def test_equal_weight_shares():
    # 100万/15/10元=6666.7 -> 整百 6600
    assert equal_weight_shares(1_000_000, 15, 10.0) == 6600
    assert equal_weight_shares(1_000_000, 15, 999999.0) == 0  # 买不起1手
    assert equal_weight_shares(1_000_000, 15, 0.0) == 0       # 价非法
    assert equal_weight_shares(0.0, 15, 10.0) == 0
```

- [ ] **Step 2: 跑,确认失败**

Run: `cd backend && .venv/bin/python -m pytest tests/test_portfolio_rebalance.py -q`
Expected: FAIL(`ModuleNotFoundError: app.portfolio.rebalance`)

- [ ] **Step 3: 实现**

新建 `backend/app/portfolio/__init__.py`(空)。

新建 `backend/app/portfolio/rebalance.py`:

```python
"""组合再平衡纯函数:再平衡日判定、TopkDropout 买卖清单、等权定股数。不触 DB/qlib。"""
from datetime import date
from math import floor


def is_rebalance_day(as_of: date, weekday: int) -> bool:
    return as_of.weekday() == weekday


def plan_rebalance(ranked, held, *, topk: int, buffer: int):
    """ranked: list[(code, rank)](rank 从 1);held: 持仓 code 集合。
    返回 (sells, buy_candidates):
      sells = 持仓中 rank>topk+buffer 或已不在 ranked 的(排序);
      buy_candidates = 未持仓、rank 最靠前的 slots+buffer 个(slots=补满 topk 的空位)。"""
    held = set(held)
    rank_of = {c: r for c, r in ranked}
    ranked_codes = [c for c, _ in sorted(ranked, key=lambda x: x[1])]
    sells = sorted(c for c in held
                   if c not in rank_of or rank_of[c] > topk + buffer)
    remaining = len(held) - len(sells)
    slots = max(0, topk - remaining)
    if slots <= 0:
        return sells, []
    buy_candidates = [c for c in ranked_codes if c not in held][: slots + buffer]
    return sells, buy_candidates


def equal_weight_shares(equity: float, topk: int, price: float, lot: int = 100) -> int:
    if equity <= 0 or topk <= 0 or price <= 0:
        return 0
    budget = equity / topk
    return int(floor(budget / price / lot)) * lot
```

- [ ] **Step 4: 跑,确认通过**

Run: `cd backend && .venv/bin/python -m pytest tests/test_portfolio_rebalance.py -q`
Expected: PASS(7 passed)

- [ ] **Step 5: 提交**

```bash
cd /root/.openclaw/workspace/ashare-trading-board
git add backend/app/portfolio/__init__.py backend/app/portfolio/rebalance.py backend/tests/test_portfolio_rebalance.py
git commit -m "feat: 组合再平衡纯函数(再平衡日/TopkDropout清单/等权定股数)"
```

---

### Task 2: 编排 `app/portfolio/execute.py`

**Files:**
- Create: `backend/app/portfolio/execute.py`
- Test: `backend/tests/test_portfolio_execute.py`

**Interfaces:**
- Consumes: `app.portfolio.rebalance.plan_rebalance`、`equal_weight_shares`;`app.decision.llm.UsageLimitError`;`app.db.models.Decision`;`PaperBroker`(`.get_position(acct,code)`、`.buy/.sell(acct,code,price,shares,on)`)。
- Produces:
  ```python
  def rebalance_portfolio(session, as_of, ranking, holdings, *, graph, broker,
                          brief_builder, price_of, equity_of, topk, buffer,
                          risk_off=False, account_id=1) -> dict
  ```
  - `ranking: list[(code, rank)]`;`holdings: set[str]`;`graph.run(brief)->Decision(action,confidence,shares,reasoning)`;`brief_builder(codes)->list[brief(有 .code)]`;`price_of(code)->float|None`;`equity_of()->float`(读当前总权益,先卖后调用)。
  - 行为:plan→(risk_off 时清空买池)→辩论 `holdings ∪ buy_candidates`→持仓 verdict==SELL 并入卖、买候选 verdict==SELL 跳过→**先卖后买**(卖全仓;买按 `equal_weight_shares(equity_of(), topk, price)`)→每只辩论过的 code 落 `Decision` 行(先删同日同 code)。
  - status:执行买=`EXECUTED`;卖出持仓=`SOLD`;保留持仓=`HELD`;被否决买候选=`VETOED`;未用到的后备买候选=`CANDIDATE`。
  - 返回 `{"sold": [...], "bought": [...], "vetoed": [...], "held": [...], "n_debated": int}`。

- [ ] **Step 1: 写失败测试**

新建 `backend/tests/test_portfolio_execute.py`:

```python
from datetime import date
from types import SimpleNamespace
from app.db.models import Account, Position, Decision
from app.trading.broker import PaperBroker
from app.portfolio.execute import rebalance_portfolio


class _Brief:
    def __init__(self, code): self.code = code

def _brief_builder(codes):
    return [_Brief(c) for c in codes]

class _Graph:
    """按 code→action 脚本;缺省 HOLD。"""
    def __init__(self, actions=None): self.actions = actions or {}
    def run(self, brief):
        a = self.actions.get(brief.code, "HOLD")
        return SimpleNamespace(action=a, confidence=0.5, shares=0,
                               reasoning=f"{brief.code}:{a}")

def _ranked(n):
    return [(f"3000{i:02d}.SZ", i + 1) for i in range(n)]

def _seed_account(session, cash=1_000_000.0):
    session.add(Account(id=1, name="main", cash=cash)); session.commit()

def _equity_of(session, price):
    acc = session.get(Account, 1)
    mv = sum(p.shares * price for p in session.query(Position)
             .filter_by(account_id=1).all())
    return acc.cash + mv


def test_empty_holdings_buys_topk_equalweight(session):
    _seed_account(session)
    broker = PaperBroker(session)
    res = rebalance_portfolio(
        session, date(2026, 8, 17), _ranked(30), set(),
        graph=_Graph(), broker=broker, brief_builder=_brief_builder,
        price_of=lambda c: 10.0, equity_of=lambda: _equity_of(session, 10.0),
        topk=15, buffer=5)
    assert len(res["bought"]) == 15
    positions = session.query(Position).filter_by(account_id=1).all()
    assert len(positions) == 15
    assert all(p.shares == 6600 for p in positions)          # 100万/15/10 整百
    assert res["sold"] == []


def test_buy_candidate_vetoed_by_sell_is_skipped(session):
    _seed_account(session)
    broker = PaperBroker(session)
    # rank0 的 300000 辩论 SELL → 跳过,由后备补位;最终仍买满 15
    res = rebalance_portfolio(
        session, date(2026, 8, 17), _ranked(30), set(),
        graph=_Graph({"300000.SZ": "SELL"}), broker=broker,
        brief_builder=_brief_builder, price_of=lambda c: 10.0,
        equity_of=lambda: _equity_of(session, 10.0), topk=15, buffer=5)
    assert "300000.SZ" in res["vetoed"]
    assert "300000.SZ" not in res["bought"]
    assert len(res["bought"]) == 15                          # 后备补满


def test_holding_vetoed_by_sell_is_sold(session):
    _seed_account(session, cash=900_000.0)
    broker = PaperBroker(session)
    broker.buy(1, "300000.SZ", 10.0, 6600, date(2026, 8, 10))  # 已持仓,rank1
    res = rebalance_portfolio(
        session, date(2026, 8, 17), _ranked(30), {"300000.SZ"},
        graph=_Graph({"300000.SZ": "SELL"}), broker=broker,
        brief_builder=_brief_builder, price_of=lambda c: 10.0,
        equity_of=lambda: _equity_of(session, 10.0), topk=15, buffer=5)
    assert "300000.SZ" in res["sold"]
    assert session.query(Position).filter_by(code="300000.SZ").first() is None


def test_risk_off_sells_only_no_buys(session):
    _seed_account(session, cash=900_000.0)
    broker = PaperBroker(session)
    broker.buy(1, "300021.SZ", 10.0, 6600, date(2026, 8, 10))   # rank22>20 → 应卖
    res = rebalance_portfolio(
        session, date(2026, 8, 17), _ranked(30), {"300021.SZ"},
        graph=_Graph(), broker=broker, brief_builder=_brief_builder,
        price_of=lambda c: 10.0, equity_of=lambda: _equity_of(session, 10.0),
        topk=15, buffer=5, risk_off=True)
    assert res["bought"] == []                               # 停买
    assert "300021.SZ" in res["sold"]                        # TopkDropout 卖照旧


def test_decision_rows_persisted(session):
    _seed_account(session)
    broker = PaperBroker(session)
    rebalance_portfolio(
        session, date(2026, 8, 17), _ranked(30), set(),
        graph=_Graph(), broker=broker, brief_builder=_brief_builder,
        price_of=lambda c: 10.0, equity_of=lambda: _equity_of(session, 10.0),
        topk=15, buffer=5)
    rows = session.query(Decision).filter_by(as_of=date(2026, 8, 17)).all()
    assert len(rows) >= 15
    assert {r.status for r in rows} <= {"EXECUTED", "VETOED", "CANDIDATE",
                                        "HELD", "SOLD"}
    assert sum(1 for r in rows if r.status == "EXECUTED") == 15
```

- [ ] **Step 2: 跑,确认失败**

Run: `cd backend && .venv/bin/python -m pytest tests/test_portfolio_execute.py -q`
Expected: FAIL(`ModuleNotFoundError: app.portfolio.execute`)

- [ ] **Step 3: 实现**

新建 `backend/app/portfolio/execute.py`:

```python
"""再平衡编排:plan → 辩论 SELL 否决 → 先卖后买(等权)→ 落 Decision。依赖全注入,可测。"""
import traceback
from sqlalchemy import delete
from app.db.models import Decision
from app.decision.llm import UsageLimitError
from app.portfolio.rebalance import plan_rebalance, equal_weight_shares


def rebalance_portfolio(session, as_of, ranking, holdings, *, graph, broker,
                        brief_builder, price_of, equity_of, topk, buffer,
                        risk_off=False, account_id=1) -> dict:
    holdings = set(holdings)
    sells, buy_pool = plan_rebalance(ranking, holdings, topk=topk, buffer=buffer)
    if risk_off:
        buy_pool = []
    sell_set = set(sells)

    # 辩论:持仓 ∪ 买候选;取 verdict
    debate_codes = sorted(holdings | set(buy_pool))
    briefs = brief_builder(debate_codes)
    verdicts = {}
    for b in briefs:
        try:
            verdicts[b.code] = graph.run(b)
        except UsageLimitError:
            raise                                   # 全局限额:整场中止(上层重试)
        except Exception as exc:                    # noqa: BLE001
            print(f"DEBATE_SKIP {b.code}: {exc!r}", flush=True)
            traceback.print_exc()

    # 持仓 SELL 否决 → 并入卖
    for c in holdings:
        v = verdicts.get(c)
        if v is not None and v.action == "SELL":
            sell_set.add(c)

    # 补满空位:买候选按 rank 顺序取,SELL 者跳过
    remaining = len(holdings) - len(sell_set & holdings)
    slots = max(0, topk - remaining)
    buys, vetoed = [], []
    for c in buy_pool:
        v = verdicts.get(c)
        if v is not None and v.action == "SELL":
            vetoed.append(c)
            continue
        if len(buys) < slots:
            buys.append(c)

    # 执行:先卖后买
    sold = []
    for c in sorted(sell_set):
        pos = broker.get_position(account_id, c)
        if pos is None or pos.shares <= 0:
            continue
        p = price_of(c)
        if not p or p <= 0:
            continue
        try:
            broker.sell(account_id, c, p, pos.shares, as_of)
            sold.append(c)
        except Exception as exc:                    # noqa: BLE001
            print(f"SELL_SKIP {c}: {exc!r}", flush=True)

    equity = equity_of()                            # 卖后再算权益,供等权定股
    bought = []
    for c in buys:
        p = price_of(c)
        shares = equal_weight_shares(equity, topk, p or 0.0)
        if shares <= 0:
            continue
        try:
            broker.buy(account_id, c, p, shares, as_of)
            bought.append(c)
        except Exception as exc:                    # noqa: BLE001
            print(f"BUY_SKIP {c}: {exc!r}", flush=True)

    # 落 Decision 行(供 UI):先删同日同 code 再插
    held_final = sorted(holdings - set(sold))
    status_of = {}
    for c in bought:   status_of[c] = "EXECUTED"
    for c in sold:     status_of[c] = "SOLD"
    for c in held_final: status_of[c] = "HELD"
    for c in vetoed:   status_of.setdefault(c, "VETOED")
    for c in buy_pool:                              # 未用到的后备
        status_of.setdefault(c, "CANDIDATE")
    for c, st in status_of.items():
        v = verdicts.get(c)
        session.execute(delete(Decision).where(
            Decision.as_of == as_of, Decision.code == c))
        session.add(Decision(
            as_of=as_of, code=c,
            action=(v.action if v is not None else "HOLD"),
            confidence=(v.confidence if v is not None else 0.0),
            shares=0, reasoning=(v.reasoning if v is not None else ""),
            status=st, created_at=as_of))
    session.commit()

    return {"sold": sold, "bought": bought, "vetoed": vetoed,
            "held": held_final, "n_debated": len(verdicts)}
```

- [ ] **Step 4: 跑,确认通过**

Run: `cd backend && .venv/bin/python -m pytest tests/test_portfolio_execute.py -q`
Expected: PASS(5 passed)

- [ ] **Step 5: 提交**

```bash
cd /root/.openclaw/workspace/ashare-trading-board
git add backend/app/portfolio/execute.py backend/tests/test_portfolio_execute.py
git commit -m "feat: 再平衡编排(SELL否决/先卖后买/等权/落Decision)"
```

---

### Task 3: 接入夜链 `config` + `daily_full.step_rebalance`

**Files:**
- Modify: `backend/app/config.py`(新增 `rebalance_weekday`、`rebalance_buffer`;`min_confidence` 注释)
- Modify: `backend/scripts/daily_full.py`(`step_debate` → `step_rebalance`;`run_all` steps 元组)
- Test: `backend/tests/test_config_phase2.py`、新建 `backend/tests/test_step_rebalance_wiring.py`

**Interfaces:**
- Consumes: `app.portfolio.rebalance.is_rebalance_day`;`app.portfolio.execute.rebalance_portfolio`;既有 `brief_builder` 闭包、`PaperBroker`、`latest_close`、`is_risk_off`、`DiscoveryPick`、`Position`。
- Produces: `daily_full.step_rebalance()`;`run_all` steps 中 `("rebalance", step_rebalance)` 取代 `("debate", step_debate)`。

- [ ] **Step 1: 写失败测试(config)**

在 `backend/tests/test_config_phase2.py` 末尾追加:

```python
def test_rebalance_settings_defaults():
    from app.config import Settings
    s = Settings()
    assert s.rebalance_weekday == 0        # 周一
    assert s.rebalance_buffer == 5
```

- [ ] **Step 2: 跑,确认失败**

Run: `cd backend && .venv/bin/python -m pytest tests/test_config_phase2.py -q`
Expected: FAIL(`AttributeError: ... rebalance_weekday`)

- [ ] **Step 3: 实现 config**

在 `backend/app/config.py` 的 `Settings` 中,`buy_trend_tol` 之后加:

```python
    rebalance_weekday: int = 0             # 周度再平衡日(0=周一);其余交易日持有不动
    rebalance_buffer: int = 5             # TopkDropout 缓冲:持仓跌出 topk+buffer 名才卖
```

把 `min_confidence` 现有注释 `# BUY/SELL 自动执行的置信度门` 改为:
`# 置信度门(仅 UI 手动单票 run_one_decision 用;夜链已改系统化 TopkDropout,不再用它)`

- [ ] **Step 4: 跑,确认通过**

Run: `cd backend && .venv/bin/python -m pytest tests/test_config_phase2.py -q`
Expected: PASS

- [ ] **Step 5: 写失败测试(接线结构守卫)**

新建 `backend/tests/test_step_rebalance_wiring.py`:

```python
def test_run_all_uses_rebalance_step_not_debate():
    # 结构守卫:夜链已切系统化再平衡,不应再挂旧的逐股 debate step
    import inspect
    import scripts.daily_full as df
    src = inspect.getsource(df.run_all)
    assert '"rebalance"' in src and "step_rebalance" in src
    assert '("debate"' not in src
    assert hasattr(df, "step_rebalance")


def test_step_rebalance_skips_non_rebalance_day(monkeypatch, capsys):
    # 非再平衡日:step 早退,不触发任何重活(不建 session/不调编排)
    import scripts.daily_full as df
    from datetime import date

    called = {"rebalanced": False}
    monkeypatch.setattr(df, "rebalance_portfolio",
                        lambda *a, **k: called.__setitem__("rebalanced", True))
    # 隔离:不连真库;伪造 as_of 为周二、settings 周一再平衡
    monkeypatch.setattr(df, "_session", lambda: object())
    monkeypatch.setattr(df, "QuoteStore", lambda s: object())
    monkeypatch.setattr(df, "_as_of_for_rebalance", lambda store: date(2026, 8, 18))
    df.step_rebalance()
    assert called["rebalanced"] is False
    assert "REBALANCE_SKIP" in capsys.readouterr().out
```

- [ ] **Step 6: 跑,确认失败**

Run: `cd backend && .venv/bin/python -m pytest tests/test_step_rebalance_wiring.py -q`
Expected: FAIL(`AttributeError: step_rebalance` / `_as_of_for_rebalance`)

- [ ] **Step 7: 实现 daily_full 改写**

在 `backend/scripts/daily_full.py` 顶部导入区加:

```python
from app.portfolio.rebalance import is_rebalance_day
from app.portfolio.execute import rebalance_portfolio
```

加一个可被测试 monkeypatch 的小helper(放在 `step_debate` 之前):

```python
def _as_of_for_rebalance(store) -> "date":
    return store.trading_dates(date.today(), 1)[0]
```

把 `step_debate` 函数**整体改名为 `step_rebalance`**,并在函数**最开头**(读 s/session/store 后、算 as_of 处)插入再平衡日早退;其余候选/持仓/风控/数据增强/brief_builder 的既有代码**保留复用**,仅把结尾的 `run_daily_decisions` 调用换成 `rebalance_portfolio`。改写后关键片段:

函数签名与开头:
```python
def step_rebalance() -> None:
    s = get_settings()
    session = _session()
    store = QuoteStore(session)
    as_of = _as_of_for_rebalance(store)
    if not is_rebalance_day(as_of, s.rebalance_weekday):
        print(f"REBALANCE_SKIP 非再平衡日 {as_of}(weekday={as_of.weekday()})", flush=True)
        return
    top_date = session.scalar(select(func.max(DiscoveryPick.as_of)))
    if top_date != as_of:
        raise RuntimeError(
            f"step_rebalance: 无当日选股产物(最新={top_date}, 期望={as_of})")
    ranking = [(r.code, r.rank) for r in session.scalars(
        select(DiscoveryPick).where(DiscoveryPick.as_of == top_date)
        .order_by(DiscoveryPick.rank)).all()]
    if not ranking:
        raise RuntimeError("step_rebalance: 无 DiscoveryPick 产物")
    holds = {p.code: p for p in session.scalars(
        select(Position).where(Position.account_id == 1)).all()}
    held = set(holds)
    from app.policy.rules import is_risk_off
    off, off_reason = is_risk_off(session, as_of, dd_stop=s.dd_stop,
                                  hitrate_stop=s.hitrate_stop)
```

保留既有的"数据增强(fundamentals/financials/research 初始化)"整段(`from app.data.fundamentals ...` 到 research runner)。研报刷新的候选口径改为**再平衡辩论池**:
```python
    from app.portfolio.rebalance import plan_rebalance
    _sells, _buy_pool = plan_rebalance(ranking, held, topk=s.target_positions,
                                       buffer=s.rebalance_buffer)
    pre_candidates = sorted(held | set(_buy_pool))
```
(把原先 `pre_candidates = select_debate_candidates(...)` 那句替换为上面两句;研报刷新 `_rr.run(set(pre_candidates), as_of)` 不变。)

保留既有 `brief_builder(codes)` 闭包定义不动(它对每个 code 建 brief)。

把结尾 `_attempt()`/`run_daily_decisions`/`_retry_on_usage_limit`/summary 段替换为:
```python
    def _equity_of():
        acc = session.get(__import__("app.db.models", fromlist=["Account"]).Account, 1)
        mv = sum(p.shares * (latest_close(store, p.code, as_of) or 0.0)
                 for p in holds.values())
        return (acc.cash if acc else 0.0) + mv

    def _attempt():
        session.rollback()
        return rebalance_portfolio(
            session, as_of, ranking, held,
            graph=DecisionGraph(_llm(s), rounds=s.debate_rounds),
            broker=PaperBroker(session), brief_builder=brief_builder,
            price_of=lambda c: latest_close(store, c, as_of),
            equity_of=_equity_of, topk=s.target_positions,
            buffer=s.rebalance_buffer, risk_off=off, account_id=1)

    summary = _retry_on_usage_limit(_attempt)
    print(build_daily_summary(session, as_of, account_id=1), flush=True)
    print(f"REBALANCE_DONE {summary}", flush=True)
```
(为清晰起见,`Account` 建议改为在文件顶部 `from app.db.models import Position, DiscoveryPick, Account`,`_equity_of` 里直接用 `session.get(Account, 1)`。)

在 `run_all()` 的 steps 元组里,把 `("debate", step_debate)` 改为 `("rebalance", step_rebalance)`。

- [ ] **Step 8: 跑,确认通过**

Run: `cd backend && .venv/bin/python -m pytest tests/test_step_rebalance_wiring.py tests/test_config_phase2.py -q`
Expected: PASS

- [ ] **Step 9: 提交**

```bash
cd /root/.openclaw/workspace/ashare-trading-board
git add backend/app/config.py backend/scripts/daily_full.py backend/tests/test_config_phase2.py backend/tests/test_step_rebalance_wiring.py
git commit -m "feat: 夜链改系统化周度再平衡(step_rebalance),0.6门槛退出夜链"
```

---

### Task 4:(运维,由控制者执行)冒烟验证 + 全量回归

> 不写代码。目标:确认编排对真实数据端到端可跑、下单数量/额度正确;不动实盘账户(用临时 scratch 账户)。

- [ ] **Step 1: 全后端回归绿**

```bash
cd /root/.openclaw/workspace/ashare-trading-board/backend && .venv/bin/python -m pytest tests/ -q
```
Expected: all passed。

- [ ] **Step 2: scratch 账户端到端冒烟**(不碰实盘 account_id=1)

写一次性脚本 `/tmp/smoke_rebalance.py`:载入真实最新 `DiscoveryPick` 排名与 qlib 价格,建一个 `account_id=99` 的 100 万 scratch 账户,`graph` 用全 HOLD 的桩(不烧 LLM),调 `rebalance_portfolio(..., topk=15, buffer=5)`,断言产出 15 笔等权 BUY、scratch 持仓 15 只、现金≈0;跑完删除 account_id=99 及其持仓/成交/决策。确认无异常、数量与额度正确。

- [ ] **Step 3: 确认再平衡日设置与首次开仓时点**

`rebalance_weekday=0`(周一)。确认下一个周一夜跑(北京22:00)将是首次真实开仓;`is_risk_off` 为真则当次只卖不买。无需重启守护进程(夜链每晚重开进程,新 step 自动生效)。

---

## Self-Review

**Spec 覆盖**:
- 系统 topk15/周度/等权满仓 → Task 1(plan/sizing)+ Task 2(执行)+ Task 3(接线)✓
- 辩论仅 SELL 否决、0.6 下线 → Task 2(veto)+ Task 3(min_confidence 退出夜链)✓
- 先卖后买、fail-soft → Task 2 ✓
- 周度再平衡日早退 → Task 1(is_rebalance_day)+ Task 3(step 早退)✓
- 风控停买只卖不买 → Task 2(risk_off 清买池)✓
- 落 Decision 供 UI → Task 2 ✓
- 限额重试/per-brief 隔离 → Task 2(UsageLimitError raise + DEBATE_SKIP)+ Task 3(_retry_on_usage_limit)✓
- 缓冲带/整手/等权定股 → Task 1 ✓

**占位符扫描**:无 TBD/TODO;每个代码步给完整代码。Task 4 为运维步,给了明确命令与断言。

**类型一致性**:`plan_rebalance(ranked, held, *, topk, buffer)->(sells,buys)`、`equal_weight_shares(equity,topk,price,lot=100)`、`is_rebalance_day(as_of,weekday)`、`rebalance_portfolio(...)->dict` 在 Task 2/3 引用一致;`Decision` 字段(as_of/code/action/confidence/shares/reasoning/status/created_at)与模型一致;status 值均 ≤ String(10);`graph.run->Decision(action,confidence,shares,reasoning)` 与 graph.py 一致;`ranking` 用 `(code, rank)` 与 DiscoveryPick.rank 一致(注意:选股按 rank 升序=分数最高在前)。

**范围**:单一子系统(执行层),一个计划。
