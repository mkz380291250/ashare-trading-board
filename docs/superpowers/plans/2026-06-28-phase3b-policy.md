# Phase 3b: 策略闸(三个自动动作 + 护栏) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用 Phase 3a 的归因指标驱动三个带护栏的自动动作——因子前向IC衰减→自动重挖换产物、回撤/胜率破阈值→自动停买、持仓复合因子持续转弱→标记进辩论倾向卖出,全部审计可查、收盘推送。

**Architecture:** 纯检测函数 `policy/rules.py`(读 3a 的 factor_ic_daily/EquitySnapshot/hit_rate + DiscoveryPick 排名)→ `policy/guardrails.py` 统一审计落 `policy_actions` 表 → `policy/actions.py` 执行(重挖走 subprocess)。`step_debate` 读检测器即时行动(停买=空位置0、弱持仓=brief 标记),`step_policy`(链尾)跑重挖并把三类动作记审计+推送。

**Tech Stack:** Python 3.11, SQLAlchemy, pytest, subprocess。复用 Phase 3a `app/attribution/{forward_ic,outcomes,equity}`、`scripts/{run_factor_mining,freeze_factors}`、Phase 2 `run_daily_decisions`/`step_debate`。

## Global Constraints

- Python 3.11;不新增第三方依赖。
- 纯纸面(PaperBroker);护栏 = 可审计(policy_actions 表)+ 可解释(trigger/detail)+ 关键动作推送(收盘文本,投递由运维层);重挖换产物的回滚句柄 = freeze_factors 已把旧产物归档到 `data/factors/archive/`。
- 默认阈值(写进 Settings,实测再调):因子衰减 = 20日滚动RankIC 连续5日 < 0.02;停买 = 权益回撤 < −0.20 或 近30日胜率 < 0.40;弱持仓 = 复合因子排名跌出全市场前 50% 连续3日。`policy_auto_remine` 默认 True(自动换产物)。
- 检测函数纯读、无副作用;只有 `step_policy`/`run_remine`/`record_action` 写库或起子进程。
- 停买实现 = `step_debate` 在 risk_off 时把 `target` 降为当前持仓数(空位=0,仍辩论持仓以决定卖/持),复用 Phase 2 有界迭代,不另造停买分支。
- 弱持仓实现 = `step_debate` 给这些持仓的 brief 传 `factors={"weak_factor": True}`(`StockBrief.to_prompt` 已渲染"量价因子:"),把信号交给辩论;持仓本就每日被辩论,不强制卖。
- 失败隔离:`step_policy` 由 run_all 逐步 try/except 隔离;policy 异常只记录不拖垮当日链。
- 代码格式一律规范 `600519.SH`。
- 测试用 in-memory sqlite;需要时 seed `FactorICDaily`/`EquitySnapshot`/`DecisionOutcome`/`DiscoveryPick`/`Position`/`Account`。

---

### Task 1: PolicyAction 审计表

**Files:**
- Modify: `backend/app/db/models.py`
- Test: `backend/tests/test_policy_models.py`

**Interfaces:**
- Produces:
  - `PolicyAction` 表 `policy_actions`:`id`(pk)、`kind: str`(REMINE / RISK_OFF / WEAK_SELL)、`as_of: date`、`trigger: str`(触发指标 JSON 文本)、`detail: str`(人类可读说明,含回滚句柄)、`status: str`(default "AUTO")、`weixin_sent: bool`(default False)、`created_at: date`。

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_policy_models.py
from datetime import date
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from app.db.database import Base
import app.db.models  # noqa
from app.db.models import PolicyAction


def _sess():
    e = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(e)
    return sessionmaker(bind=e, future=True)()


def test_policy_action_roundtrip():
    s = _sess()
    s.add(PolicyAction(kind="REMINE", as_of=date(2026, 6, 28),
                       trigger='{"rolling_rank_ic": 0.011}', detail="IC衰减→重挖,旧产物归档 archive/...",
                       status="AUTO", weixin_sent=False, created_at=date(2026, 6, 28)))
    s.commit()
    row = s.scalar(select(PolicyAction))
    assert row.kind == "REMINE" and row.status == "AUTO" and row.weixin_sent is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/pytest tests/test_policy_models.py -v`
Expected: FAIL with `ImportError: cannot import name 'PolicyAction'`

- [ ] **Step 3: Write minimal implementation**

Append to `backend/app/db/models.py` (mirror existing style; `Boolean` is already imported from Phase 3a Task 1):

```python
class PolicyAction(Base):
    __tablename__ = "policy_actions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(16))
    as_of: Mapped[date] = mapped_column(Date)
    trigger: Mapped[str] = mapped_column(String, default="{}")
    detail: Mapped[str] = mapped_column(String, default="")
    status: Mapped[str] = mapped_column(String(12), default="AUTO")
    weixin_sent: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[date] = mapped_column(Date)


Index("ix_policy_actions_as_of", PolicyAction.as_of)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/bin/pytest tests/test_policy_models.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/db/models.py backend/tests/test_policy_models.py
git commit -m "feat(policy): policy_actions audit model"
```

---

### Task 2: mark_to_market 幂等(去重 EquitySnapshot)

**Files:**
- Modify: `backend/app/trading/broker.py`
- Test: `backend/tests/test_broker_mark_idempotent.py`

**Interfaces:**
- Consumes: 现有 `PaperBroker.mark_to_market(account_id, prices, on)`。
- Produces: `mark_to_market` 改为按 `(account_id, on)` 去重——写新快照前先删除同账户同日的旧快照(同日重跑 run_all 不再累积重复行)。返回值不变(EquitySnapshot)。

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_broker_mark_idempotent.py
from datetime import date
from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.db.database import Base
import app.db.models  # noqa
from app.db.models import Account, EquitySnapshot
from app.trading.broker import PaperBroker
from app.data.prices import DictPriceProvider


def _sess():
    e = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                      poolclass=StaticPool, future=True)
    Base.metadata.create_all(e)
    s = sessionmaker(bind=e, future=True)()
    s.add(Account(id=1, name="main", cash=1000.0)); s.commit()
    return s


def test_mark_to_market_idempotent_same_day():
    s = _sess()
    b = PaperBroker(s)
    b.mark_to_market(1, DictPriceProvider({}), date(2026, 6, 28))
    b.mark_to_market(1, DictPriceProvider({}), date(2026, 6, 28))
    n = s.scalar(select(func.count()).select_from(EquitySnapshot).where(
        EquitySnapshot.account_id == 1, EquitySnapshot.as_of == date(2026, 6, 28)))
    assert n == 1                                  # 同日只留一条
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/pytest tests/test_broker_mark_idempotent.py -v`
Expected: FAIL — `assert 2 == 1`(当前无去重)

- [ ] **Step 3: Write minimal implementation**

In `backend/app/trading/broker.py`, at the start of `mark_to_market` (after computing `acc`/`positions`, before constructing `snap`), delete any existing same-day snapshot. Add `delete` to the sqlalchemy import (`from sqlalchemy import select, delete`). Insert before `snap = EquitySnapshot(...)`:

```python
        self.s.execute(delete(EquitySnapshot).where(
            EquitySnapshot.account_id == account_id, EquitySnapshot.as_of == on))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/bin/pytest tests/test_broker_mark_idempotent.py tests/test_broker.py -v`
Expected: PASS(新测试 + 既有 broker 测试无回归)

- [ ] **Step 5: Commit**

```bash
git add backend/app/trading/broker.py backend/tests/test_broker_mark_idempotent.py
git commit -m "fix(broker): mark_to_market idempotent per (account, as_of)"
```

---

### Task 3: rules — 因子衰减检测

**Files:**
- Create: `backend/app/policy/__init__.py`
- Create: `backend/app/policy/rules.py`
- Test: `backend/tests/test_policy_factor_decay.py`

**Interfaces:**
- Consumes: Phase 3a `app/attribution/forward_ic.latest_rolling_rank_ic(session, *, as_of, window)`、`FactorICDaily`。
- Produces:
  - `factor_decayed(session, as_of: date, *, window: int = 20, consecutive: int = 5, threshold: float = 0.02) -> bool` — 取 `factor_ic_daily` 中 `as_of` 当日及之前最近 `consecutive` 个不同 as_of;对每个 d 用 `latest_rolling_rank_ic(session, as_of=d, window=window)` 求 20 日滚动 RankIC;**全部非 None 且 < threshold** 才判定衰减;历史不足 `consecutive` 天 → False。

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_policy_factor_decay.py
from datetime import date, timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.db.database import Base
import app.db.models  # noqa
from app.db.models import FactorICDaily
from app.policy.rules import factor_decayed


def _sess():
    e = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(e)
    return sessionmaker(bind=e, future=True)()


def _seed_ic(s, start: date, rank_ics: list[float]):
    for i, r in enumerate(rank_ics):
        s.add(FactorICDaily(as_of=start + timedelta(days=i), ic=r, rank_ic=r, n=100))
    s.commit()


def test_decayed_when_last5_below_threshold():
    s = _sess()
    d0 = date(2026, 6, 1)
    _seed_ic(s, d0, [0.01] * 8)          # 连续低
    assert factor_decayed(s, d0 + timedelta(days=7), window=3, consecutive=5,
                          threshold=0.02) is True


def test_not_decayed_when_recent_recovers():
    s = _sess()
    d0 = date(2026, 6, 1)
    _seed_ic(s, d0, [0.01, 0.01, 0.01, 0.01, 0.01, 0.05, 0.06, 0.07])  # 近端回升
    assert factor_decayed(s, d0 + timedelta(days=7), window=3, consecutive=5,
                          threshold=0.02) is False


def test_not_decayed_insufficient_history():
    s = _sess()
    d0 = date(2026, 6, 1)
    _seed_ic(s, d0, [0.01, 0.01])        # 不足 consecutive
    assert factor_decayed(s, d0 + timedelta(days=1), window=3, consecutive=5,
                          threshold=0.02) is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/pytest tests/test_policy_factor_decay.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.policy'`

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/policy/__init__.py
```

```python
# backend/app/policy/rules.py
"""策略闸检测函数(纯读、无副作用):因子衰减 / 风控停买 / 弱持仓。
供 step_debate 即时行动与 step_policy 审计。"""
from datetime import date
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.db.models import FactorICDaily
from app.attribution.forward_ic import latest_rolling_rank_ic


def factor_decayed(session: Session, as_of: date, *, window: int = 20,
                   consecutive: int = 5, threshold: float = 0.02) -> bool:
    days = session.scalars(select(FactorICDaily.as_of).where(
        FactorICDaily.as_of <= as_of).order_by(
        FactorICDaily.as_of.desc()).limit(consecutive)).all()
    if len(days) < consecutive:
        return False
    for d in days:
        ric = latest_rolling_rank_ic(session, as_of=d, window=window)
        if ric is None or ric >= threshold:
            return False
    return True
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/bin/pytest tests/test_policy_factor_decay.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/app/policy/__init__.py backend/app/policy/rules.py backend/tests/test_policy_factor_decay.py
git commit -m "feat(policy): factor decay detection (rolling RankIC consecutive below threshold)"
```

---

### Task 4: rules — 风控停买 + 弱持仓检测

**Files:**
- Modify: `backend/app/policy/rules.py`
- Test: `backend/tests/test_policy_riskoff_weak.py`

**Interfaces:**
- Consumes: Phase 3a `app/attribution/equity.current_drawdown`、`app/attribution/outcomes.hit_rate`;`EquitySnapshot`、`DiscoveryPick`。
- Produces:
  - `is_risk_off(session, as_of: date, *, account_id: int = 1, dd_stop: float = 0.20, hitrate_stop: float = 0.40, hit_window: int = 30) -> tuple[bool, str]` — 取该账户 `EquitySnapshot.total` 升序序列算 `current_drawdown`;取 `hit_rate(session, window=hit_window, as_of=as_of)`;回撤 < −dd_stop 或 胜率 < hitrate_stop 即 risk_off,返回 (True, 原因串);否则 (False, "")。
  - `weak_holdings(session, held: set[str], as_of: date, *, pctl: float = 0.50, consecutive: int = 3) -> list[str]` — 取最近 `consecutive` 个不同 DiscoveryPick as_of;对每个持仓 code,若在每一天的截面里其 `rank / 当日总数 > pctl`(或当日不在截面=视为弱)则判弱;历史不足 `consecutive` 天 → 空列表。返回排序后的弱持仓 code 列表。

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_policy_riskoff_weak.py
from datetime import date, timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.db.database import Base
import app.db.models  # noqa
from app.db.models import Account, EquitySnapshot, DecisionOutcome, DiscoveryPick
from app.policy.rules import is_risk_off, weak_holdings


def _sess():
    e = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                      poolclass=StaticPool, future=True)
    Base.metadata.create_all(e)
    s = sessionmaker(bind=e, future=True)()
    s.add(Account(id=1, name="main", cash=0.0)); s.commit()
    return s


def test_risk_off_on_drawdown():
    s = _sess()
    s.add(EquitySnapshot(account_id=1, as_of=date(2026, 6, 1), cash=0, market_value=0, total=100.0))
    s.add(EquitySnapshot(account_id=1, as_of=date(2026, 6, 2), cash=0, market_value=0, total=75.0))  # -25%
    s.commit()
    off, reason = is_risk_off(s, date(2026, 6, 2), dd_stop=0.20, hitrate_stop=0.40)
    assert off is True and "回撤" in reason


def test_risk_off_on_low_hitrate():
    s = _sess()
    s.add(EquitySnapshot(account_id=1, as_of=date(2026, 6, 2), cash=0, market_value=0, total=100.0))
    for i in range(5):  # 5 条 outcome,全未命中 → 胜率 0
        s.add(DecisionOutcome(decision_id=i + 1, code=f"C{i}.SH", decided_on=date(2026, 6, 1),
                              action="BUY", entry_close=10.0, ret_t5=-0.05, hit=False,
                              last_updated=date(2026, 6, 2)))
    s.commit()
    off, reason = is_risk_off(s, date(2026, 6, 2), dd_stop=0.20, hitrate_stop=0.40)
    assert off is True and "胜率" in reason


def test_not_risk_off_when_healthy():
    s = _sess()
    s.add(EquitySnapshot(account_id=1, as_of=date(2026, 6, 2), cash=0, market_value=0, total=110.0))
    off, reason = is_risk_off(s, date(2026, 6, 2))
    assert off is False


def _seed_pick(s, as_of, ranked_codes):
    total = len(ranked_codes)
    for rank, code in enumerate(ranked_codes, 1):
        s.add(DiscoveryPick(as_of=as_of, code=code, rank=rank, score=float(total - rank), factors="{}"))


def test_weak_holdings_persistently_bottom():
    s = _sess()
    d = [date(2026, 6, 1) + timedelta(days=i) for i in range(3)]
    # 4 只票,持仓 LOW.SH 连续3天排第4(rank/4=1.0 > 0.5)→ 弱;TOP.SH 排第1 → 不弱
    for dd in d:
        _seed_pick(s, dd, ["TOP.SH", "A.SH", "B.SH", "LOW.SH"])
    s.commit()
    weak = weak_holdings(s, {"TOP.SH", "LOW.SH"}, d[-1], pctl=0.50, consecutive=3)
    assert weak == ["LOW.SH"]


def test_weak_holdings_insufficient_history():
    s = _sess()
    _seed_pick(s, date(2026, 6, 1), ["TOP.SH", "LOW.SH"])
    s.commit()
    assert weak_holdings(s, {"LOW.SH"}, date(2026, 6, 1), consecutive=3) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/pytest tests/test_policy_riskoff_weak.py -v`
Expected: FAIL with `ImportError: cannot import name 'is_risk_off'`

- [ ] **Step 3: Write minimal implementation**

Append to `backend/app/policy/rules.py`:

```python
from app.db.models import EquitySnapshot, DiscoveryPick
from app.attribution.equity import current_drawdown
from app.attribution.outcomes import hit_rate


def is_risk_off(session: Session, as_of: date, *, account_id: int = 1,
                dd_stop: float = 0.20, hitrate_stop: float = 0.40,
                hit_window: int = 30) -> tuple[bool, str]:
    totals = session.scalars(select(EquitySnapshot.total).where(
        EquitySnapshot.account_id == account_id,
        EquitySnapshot.as_of <= as_of).order_by(EquitySnapshot.as_of)).all()
    dd = current_drawdown(list(totals))
    if dd is not None and dd < -dd_stop:
        return (True, f"回撤 {dd*100:.1f}% 破 {-dd_stop*100:.0f}%")
    hr = hit_rate(session, window=hit_window, as_of=as_of)
    if hr is not None and hr < hitrate_stop:
        return (True, f"胜率 {hr*100:.0f}% 破 {hitrate_stop*100:.0f}%")
    return (False, "")


def weak_holdings(session: Session, held: set[str], as_of: date, *,
                  pctl: float = 0.50, consecutive: int = 3) -> list[str]:
    days = session.scalars(select(DiscoveryPick.as_of).where(
        DiscoveryPick.as_of <= as_of).distinct().order_by(
        DiscoveryPick.as_of.desc()).limit(consecutive)).all()
    if len(days) < consecutive:
        return []
    weak = []
    for code in held:
        is_weak = True
        for d in days:
            picks = session.scalars(select(DiscoveryPick).where(
                DiscoveryPick.as_of == d)).all()
            total = len(picks)
            row = next((p for p in picks if p.code == code), None)
            # 不在当日截面=视为弱;在截面则看百分位是否跌出前 pctl
            if row is not None and total and (row.rank / total) <= pctl:
                is_weak = False
                break
        if is_weak:
            weak.append(code)
    return sorted(weak)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/bin/pytest tests/test_policy_riskoff_weak.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/app/policy/rules.py backend/tests/test_policy_riskoff_weak.py
git commit -m "feat(policy): risk-off (drawdown/hit-rate) + weak-holding detection"
```

---

### Task 5: guardrails 审计 + actions 重挖执行器

**Files:**
- Create: `backend/app/policy/guardrails.py`
- Create: `backend/app/policy/actions.py`
- Test: `backend/tests/test_policy_guardrails.py`

**Interfaces:**
- Consumes: Task 1 `PolicyAction`;`scripts/run_factor_mining.py`、`scripts/freeze_factors.py`(subprocess)。
- Produces:
  - `record_action(session, kind: str, as_of: date, trigger: dict, detail: str, *, status: str = "AUTO") -> PolicyAction` — 把动作以 JSON trigger 落 `policy_actions` 表并返回(审计入口;weixin_sent 初始 False)。
  - `run_remine(*, root=None) -> int` — 依次 subprocess 跑 `scripts/run_factor_mining.py` 再 `scripts/freeze_factors.py`(后者会归档旧产物=回滚句柄);返回 0 成功、非 0 失败(任一步非零即返回其码,不抛)。`root` 默认仓库 backend 目录。

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_policy_guardrails.py
import json
from datetime import date
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from app.db.database import Base
import app.db.models  # noqa
from app.db.models import PolicyAction
from app.policy.guardrails import record_action


def _sess():
    e = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(e)
    return sessionmaker(bind=e, future=True)()


def test_record_action_persists_audit():
    s = _sess()
    pa = record_action(s, "RISK_OFF", date(2026, 6, 28),
                       {"drawdown": -0.22}, "回撤 -22% 破 20%,当日停买")
    assert pa.id is not None
    row = s.scalar(select(PolicyAction))
    assert row.kind == "RISK_OFF" and row.status == "AUTO"
    assert json.loads(row.trigger)["drawdown"] == -0.22
    assert row.weixin_sent is False
```

```python
# (same file) — run_remine 用 monkeypatch 截 subprocess,不真起进程
def test_run_remine_invokes_mining_then_freeze(monkeypatch):
    from app.policy import actions
    calls = []

    class _R:
        returncode = 0

    def fake_run(cmd, **kw):
        calls.append(cmd)
        return _R()

    monkeypatch.setattr(actions.subprocess, "run", fake_run)
    rc = actions.run_remine()
    assert rc == 0
    assert len(calls) == 2                       # mining 然后 freeze
    assert "run_factor_mining.py" in " ".join(map(str, calls[0]))
    assert "freeze_factors.py" in " ".join(map(str, calls[1]))


def test_run_remine_stops_on_mining_failure(monkeypatch):
    from app.policy import actions
    calls = []

    class _R:
        def __init__(self, rc): self.returncode = rc

    def fake_run(cmd, **kw):
        calls.append(cmd)
        return _R(1)                             # mining 失败

    monkeypatch.setattr(actions.subprocess, "run", fake_run)
    rc = actions.run_remine()
    assert rc == 1
    assert len(calls) == 1                        # freeze 不再执行
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/pytest tests/test_policy_guardrails.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.policy.guardrails'`

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/policy/guardrails.py
"""策略动作统一审计入口:落 policy_actions 表。关键动作的 weixin 推送由 step_policy
打印交运维层投递(初始 weixin_sent=False)。"""
import json
from datetime import date
from sqlalchemy.orm import Session
from app.db.models import PolicyAction


def record_action(session: Session, kind: str, as_of: date, trigger: dict,
                  detail: str, *, status: str = "AUTO") -> PolicyAction:
    pa = PolicyAction(kind=kind, as_of=as_of, trigger=json.dumps(trigger, ensure_ascii=False),
                      detail=detail, status=status, weixin_sent=False, created_at=as_of)
    session.add(pa)
    session.commit()
    return pa
```

```python
# backend/app/policy/actions.py
"""策略动作执行器。run_remine 走 subprocess 跑挖掘+冻结(冻结归档旧产物=回滚句柄)。"""
import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]      # backend/
_PY = sys.executable


def run_remine(*, root: Path | None = None) -> int:
    root = root or _ROOT
    mining = subprocess.run([_PY, str(root / "scripts" / "run_factor_mining.py")], cwd=root)
    if mining.returncode != 0:
        return mining.returncode
    freeze = subprocess.run([_PY, str(root / "scripts" / "freeze_factors.py")], cwd=root)
    return freeze.returncode
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/bin/pytest tests/test_policy_guardrails.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/app/policy/guardrails.py backend/app/policy/actions.py backend/tests/test_policy_guardrails.py
git commit -m "feat(policy): guardrails audit + run_remine executor (mining then freeze)"
```

---

### Task 6: Settings 策略闸配置项

**Files:**
- Modify: `backend/app/config.py`
- Test: `backend/tests/test_config_phase3b.py`

**Interfaces:**
- Produces: `Settings` 新增 `policy_auto_remine: bool = True`、`ic_decay_window: int = 20`、`ic_decay_consecutive: int = 5`、`ic_decay_threshold: float = 0.02`、`dd_stop: float = 0.20`、`hitrate_stop: float = 0.40`、`weak_pctl: float = 0.50`、`weak_consecutive: int = 3`。

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_config_phase3b.py
from app.config import Settings


def test_phase3b_defaults():
    s = Settings()
    assert s.policy_auto_remine is True
    assert s.ic_decay_window == 20 and s.ic_decay_consecutive == 5
    assert s.ic_decay_threshold == 0.02
    assert s.dd_stop == 0.20 and s.hitrate_stop == 0.40
    assert s.weak_pctl == 0.50 and s.weak_consecutive == 3
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/pytest tests/test_config_phase3b.py -v`
Expected: FAIL with `AttributeError: 'Settings' object has no attribute 'policy_auto_remine'`

- [ ] **Step 3: Write minimal implementation**

Add to the `Settings` class in `backend/app/config.py` (after the Phase 2 knobs `max_debate`):

```python
    policy_auto_remine: bool = True        # 因子衰减时自动重挖换产物
    ic_decay_window: int = 20              # 滚动 RankIC 窗口
    ic_decay_consecutive: int = 5          # 连续低于阈值天数
    ic_decay_threshold: float = 0.02       # 滚动 RankIC 阈值
    dd_stop: float = 0.20                  # 回撤停买阈值
    hitrate_stop: float = 0.40             # 胜率停买阈值
    weak_pctl: float = 0.50                # 持仓弱因子百分位门
    weak_consecutive: int = 3              # 弱因子连续天数
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/bin/pytest tests/test_config_phase3b.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/config.py backend/tests/test_config_phase3b.py
git commit -m "feat(config): phase3b policy knobs"
```

---

### Task 7: 接入 daily_full(step_debate 停买/弱标记 + step_policy)

**Files:**
- Modify: `backend/scripts/daily_full.py`
- Test: `backend/tests/test_daily_full_phase3b.py`

**Interfaces:**
- Consumes: Task 3 `factor_decayed`、Task 4 `is_risk_off`/`weak_holdings`、Task 5 `record_action`/`run_remine`、Settings 配置项。
- Produces:
  - `step_debate` 改:辩论前 `off, _ = is_risk_off(session, as_of, dd_stop=s.dd_stop, hitrate_stop=s.hitrate_stop)`,off 时把传给 `run_daily_decisions` 的 `target` 设为 `len(held)`(空位=0,停买);用 `weak_holdings(session, held, as_of, pctl=s.weak_pctl, consecutive=s.weak_consecutive)` 得弱持仓,brief_builder 对弱持仓 code 传 `factors={"weak_factor": True}`(其余 `{}`)。
  - `step_policy()` ★新:`factor_decayed(...)` 为真且 `s.policy_auto_remine` → `record_action("REMINE",...)` + `run_remine()`;`is_risk_off` 为真 → `record_action("RISK_OFF",...)`;`weak_holdings` 非空 → `record_action("WEAK_SELL",...)`;打印策略摘要(供 weixin)。追加进 run_all 元组末尾(在 `step_attribution` 之后)。

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_daily_full_phase3b.py
import scripts.daily_full as df


def test_run_all_appends_step_policy(monkeypatch):
    calls = []
    for name in ("step_quotes", "step_qlib", "step_tracklist", "step_select",
                 "step_debate", "step_mark", "step_attribution", "step_policy"):
        monkeypatch.setattr(df, name, (lambda n=name: lambda: calls.append(n))())
    df.run_all()
    assert calls[-1] == "step_policy"
    assert calls == ["step_quotes", "step_qlib", "step_tracklist", "step_select",
                     "step_debate", "step_mark", "step_attribution", "step_policy"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/pytest tests/test_daily_full_phase3b.py -v`
Expected: FAIL — `AttributeError: module 'scripts.daily_full' has no attribute 'step_policy'`

- [ ] **Step 3: Write minimal implementation**

In `backend/scripts/daily_full.py`:

(a) In `step_debate`, after `held`/`holds` are computed and before constructing `brief_builder`/calling `run_daily_decisions`, add risk-off + weak detection:

```python
    from app.policy.rules import is_risk_off, weak_holdings
    off, off_reason = is_risk_off(session, as_of, dd_stop=s.dd_stop,
                                  hitrate_stop=s.hitrate_stop)
    weak = set(weak_holdings(session, held, as_of, pctl=s.weak_pctl,
                             consecutive=s.weak_consecutive))
    target = len(held) if off else s.target_positions
```

Change `brief_builder` to tag weak holdings (replace the `build_brief(... {}, {}, holding)` factors arg):

```python
        def brief_builder(codes):
            start = date(as_of.year - 1, as_of.month, as_of.day)
            out = []
            for code in codes:
                bars = store.get_bars(code, start, as_of)
                closes = [b.close for b in bars][-20:]
                h = holds.get(code)
                holding = {"shares": h.shares, "cost": h.cost} if h else None
                factors = {"weak_factor": True} if code in weak else {}
                out.append(build_brief(code, closes, factors, {}, holding))
            return out
```

And change the `run_daily_decisions(... target=s.target_positions ...)` call to use the computed `target`:

```python
    summary = run_daily_decisions(
        session, as_of, ranking, held, graph=DecisionGraph(_llm(s), rounds=s.debate_rounds),
        brief_builder=brief_builder, broker=PaperBroker(session),
        price_of=lambda c: latest_close(store, c, as_of),
        target=target, quality_pctl=s.quality_pctl,
        min_confidence=s.min_confidence, max_debate=s.max_debate, account_id=1)
```

(b) Add `step_policy` (after `step_attribution`):

```python
def step_policy() -> None:
    from app.policy.rules import factor_decayed, is_risk_off, weak_holdings
    from app.policy.guardrails import record_action
    from app.policy.actions import run_remine
    s = get_settings()
    session = _session()
    store = QuoteStore(session)
    as_of = store.trading_dates(date.today(), 1)[0]
    held = {p.code for p in session.scalars(
        select(Position).where(Position.account_id == 1)).all()}
    notes = []
    if factor_decayed(session, as_of, window=s.ic_decay_window,
                      consecutive=s.ic_decay_consecutive, threshold=s.ic_decay_threshold):
        ric = latest_rolling_rank_ic(session, as_of=as_of, window=s.ic_decay_window)
        record_action(session, "REMINE", as_of, {"rolling_rank_ic": ric},
                      "因子前向IC衰减→自动重挖换产物(旧产物已归档 data/factors/archive/)")
        notes.append("因子衰减→重挖")
        if s.policy_auto_remine:
            rc = run_remine()
            notes.append(f"重挖完成 rc={rc}")
    off, off_reason = is_risk_off(session, as_of, dd_stop=s.dd_stop, hitrate_stop=s.hitrate_stop)
    if off:
        record_action(session, "RISK_OFF", as_of, {"reason": off_reason}, f"风控停买:{off_reason}")
        notes.append(f"停买({off_reason})")
    weak = weak_holdings(session, held, as_of, pctl=s.weak_pctl, consecutive=s.weak_consecutive)
    if weak:
        record_action(session, "WEAK_SELL", as_of, {"codes": weak},
                      f"持仓弱因子标卖候选:{weak}")
        notes.append(f"弱持仓 {len(weak)} 只")
    print(f"POLICY_DONE {as_of} " + ("; ".join(notes) if notes else "无动作"), flush=True)
```

Add `from app.attribution.forward_ic import latest_rolling_rank_ic` at the top of daily_full.py (module-level import is safe — it's DB-only, no qlib).

(c) Extend the `run_all` step tuple:

```python
    for step in (step_quotes, step_qlib, step_tracklist, step_select,
                 step_debate, step_mark, step_attribution, step_policy):
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/bin/pytest tests/test_daily_full_phase3b.py tests/test_daily_full_phase3.py tests/test_daily_full_phase2.py tests/test_daily_full.py -v`
Expected: PASS(新 step_policy 顺序测试 + 既有 daily_full 顺序/隔离测试无回归)

- [ ] **Step 5: Commit**

```bash
git add backend/scripts/daily_full.py backend/tests/test_daily_full_phase3b.py
git commit -m "feat(daily): step_policy auto-actions + risk-off stop-buy + weak-holding brief tags"
```

---

### Task 8: 全后端回归 + 策略闸集成冒烟

**Files:**
- Test: `backend/tests/test_policy_integration.py`

**Interfaces:**
- Consumes: Task 3/4 检测函数;真实 DB。

- [ ] **Step 1: Write the integration test**

```python
# backend/tests/test_policy_integration.py
import pytest
from datetime import date
from app.db.database import make_engine, make_session_factory
import app.db.models  # noqa
from app.data.quote_store import QuoteStore
from app.policy.rules import factor_decayed, is_risk_off, weak_holdings

pytestmark = pytest.mark.integration


def test_policy_rules_run_on_real_db():
    session = make_session_factory(make_engine())()
    store = QuoteStore(session)
    as_of = store.trading_dates(date.today(), 1)[0]
    # 真实库上三个检测器都不应抛错
    dec = factor_decayed(session, as_of)
    off, _ = is_risk_off(session, as_of)
    weak = weak_holdings(session, set(), as_of)
    assert isinstance(dec, bool) and isinstance(off, bool) and weak == []
```

- [ ] **Step 2: Run integration + full suite**

Run: `cd backend && .venv/bin/pytest tests/test_policy_integration.py -v -m integration`
Expected: PASS(真实库可连且 policy_actions 等表已建时);新表缺失则按 Phase 3a 同法 `Base.metadata.create_all(make_engine())` 建一次。
Run: `cd backend && .venv/bin/pytest -q`
Expected: 全绿(新增 policy 测试 + 既有全套无回归)。注:`-m "not integration"` 可只跑快测;默认全跑含真实 qlib 集成耗时数分钟,属正常。

- [ ] **Step 3: Commit**

```bash
git add backend/tests/test_policy_integration.py
git commit -m "test(policy): integration detectors on real db + full regression"
```

---

## Self-Review

**Spec coverage(对照 spec §7.2 / §7.3):**
- §7.2.1 因子衰减→自动重挖(滚动20日RankIC连5日<0.02,自动换+归档+通知)→ Task 3(检测)+ Task 5(run_remine)+ Task 7(step_policy 触发+审计)✓
- §7.2.2 风控→自动停买(回撤>20%或胜率<40%,自动解除)→ Task 4(is_risk_off)+ Task 7(step_debate target=len(held) 停买;每日重算=自动解除)✓
- §7.2.3 持仓弱因子→自动标卖(跌出前50%连3日,进辩论)→ Task 4(weak_holdings)+ Task 7(brief 标 weak_factor,持仓本就被辩论)✓
- §7.3 guardrails 统一入口(审计 policy_actions / 关键动作推送 / 回滚句柄)→ Task 1(表)+ Task 5(record_action)+ Task 7(step_policy 打印供推送;回滚=freeze 归档)✓
- §7.4 验收(注入条件验证三动作触发、审计落库)→ Task 3/4/5/7 单测 + Task 8 集成 ✓
- 3a 延后项 step_mark 去重 → Task 2 ✓

**范围说明 / 有意缩减:**
- "可一键回滚":纸面阶段实现为 **freeze_factors 自动归档旧产物到 `data/factors/archive/`**(reversibility 句柄),不建自动回滚端点(YAGNI;接实盘再做)。PolicyAction.detail 记录归档位置。
- 弱持仓"自动标卖"实现为**把弱信号注入 brief 交辩论决定卖出**(持仓 Phase 2 本就每日被辩论),不绕过辩论直接卖——符合 spec"辩论确认SELL即自动执行"。
- 风控停买与弱持仓检测在 step_debate(即时行动)与 step_policy(审计)各算一次(纯读、廉价),换取职责清晰。

**Placeholder scan:** 无 TBD/TODO;每代码步含完整代码与预期输出。

**Type consistency:**
- `factor_decayed(session, as_of, *, window, consecutive, threshold)->bool` Task 3 定义,Task 7 调用一致。
- `is_risk_off(session, as_of, *, account_id, dd_stop, hitrate_stop, hit_window)->(bool,str)`、`weak_holdings(session, held, as_of, *, pctl, consecutive)->list[str]` Task 4 定义,Task 7 调用一致。
- `record_action(session, kind, as_of, trigger, detail, *, status)->PolicyAction`、`run_remine(*, root)->int` Task 5 定义,Task 7 调用一致。
- Settings 字段 Task 6 定义,Task 7 经 `s.<field>` 引用一致。
- `PolicyAction` 字段 Task 1 定义,Task 5/7 引用一致。

**执行前需核对(给实现者):**
1. 已核实:`Boolean` 自 Phase 3a 已导入 models.py(Task 1 直接用)。
2. 已核实:`StockBrief.to_prompt` 渲染 `量价因子: {json.dumps(self.factors)}` —— brief 的 `factors={"weak_factor": True}` 会出现在辩论 prompt 里(Task 7)。
3. 已核实:daily_full.py 顶部已有 `from sqlalchemy import select, func`、`PY/ROOT/subprocess`、`QuoteStore`、`get_settings`、`Position`、`build_brief`、`run_daily_decisions`、`PaperBroker`、`DecisionGraph`、`latest_close`(Phase 2);Task 7 仅新增 `latest_rolling_rank_ic` 顶部导入与 policy 模块的函数内导入。
4. step_policy 的 run_remine 真跑会起 qlib 子进程(慢);单测用 monkeypatch 截 subprocess,集成测试只测检测器不触发 run_remine。
