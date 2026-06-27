# Phase 3a: 归因度量层(决策胜率 / 因子前向IC / 回撤) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给闭环装上度量层——回填每条 BUY/SELL 决策的后向收益与命中、计算复合因子每日前向 IC/RankIC、算权益回撤与滚动胜率,接进 daily_full 并进日报。这是 Phase 3b 策略闸读取的基础。

**Architecture:** 纯计算函数(后向收益/命中、单日 IC、回撤、滚动胜率)与 DB 回填(backfill)分离,纯函数可单测、回填用 in-memory sqlite 测。新增两张表 `decision_outcomes`、`factor_ic_daily`;回撤/胜率为纯计算不落表。`step_attribution` 接进 `run_all` 链尾,日报追加胜率与最新前向 IC。

**Tech Stack:** Python 3.11, SQLAlchemy, pandas, pytest。复用 `app/screener/filters.forward_return`、`app/data/quote_store.QuoteStore`(`get_bars`/`trading_dates`)、`app/db/models`(Decision/DiscoveryPick/EquitySnapshot)。

## Global Constraints

- Python 3.11;不新增第三方依赖。
- 后向收益用收盘价对收盘价:`entry = close(decided_on)`,`ret_tk = close(decided_on + k 交易日)/entry − 1`(复用 `forward_return`)。命中以 t5 为准:BUY 命中 = ret_t5 > 0;SELL 命中 = ret_t5 < 0(卖在下跌前)。
- 只回填 status == "APPROVED" 的 BUY/SELL 决策(真正执行的);HOLD/LOW_CONF/PENDING 不计。
- 前向 IC:对每个有 DiscoveryPick 且 5 日前向窗口已走完的 as_of,算该日 `DiscoveryPick.score` 截面与各 code 实现 5 日前向收益的 IC(Pearson)与 RankIC(Spearman),一行一 as_of。截面 < 2 / score 或 ret 无方差 → IC 记 None。
- 回填幂等:按主键 upsert(decision_outcomes 按 decision_id,factor_ic_daily 按 as_of),重复跑覆盖不累积。
- 失败隔离:`step_attribution` 由 `run_all` 的逐步 try/except 隔离;归因失败不影响当日交易链。
- 代码格式一律规范 `600519.SH`。
- 测试用 in-memory sqlite(`create_engine("sqlite:///:memory:")` + `Base.metadata.create_all`);需要时 seed `DailyQuote`/`Decision`/`DiscoveryPick`/`EquitySnapshot`。

---

### Task 1: 归因表 DecisionOutcome / FactorICDaily

**Files:**
- Modify: `backend/app/db/models.py`
- Test: `backend/tests/test_attribution_models.py`

**Interfaces:**
- Produces:
  - `DecisionOutcome` 表 `decision_outcomes`:`id`(pk)、`decision_id: int`(FK decisions.id,唯一)、`code: str`、`decided_on: date`、`action: str`、`entry_close: float`、`ret_t1/ret_t3/ret_t5/ret_t10: float|None`、`hit: bool|None`、`last_updated: date`。
  - `FactorICDaily` 表 `factor_ic_daily`:`as_of: date`(pk)、`ic: float|None`、`rank_ic: float|None`、`n: int`。

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_attribution_models.py
from datetime import date
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from app.db.database import Base
import app.db.models  # noqa
from app.db.models import DecisionOutcome, FactorICDaily


def _sess():
    e = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(e)
    return sessionmaker(bind=e, future=True)()


def test_decision_outcome_roundtrip():
    s = _sess()
    s.add(DecisionOutcome(decision_id=7, code="600519.SH", decided_on=date(2026, 6, 4),
                          action="BUY", entry_close=100.0, ret_t1=0.01, ret_t3=0.02,
                          ret_t5=0.03, ret_t10=None, hit=True, last_updated=date(2026, 6, 12)))
    s.commit()
    row = s.scalar(select(DecisionOutcome))
    assert row.decision_id == 7 and row.hit is True and row.ret_t10 is None


def test_factor_ic_daily_roundtrip():
    s = _sess()
    s.add(FactorICDaily(as_of=date(2026, 6, 4), ic=0.025, rank_ic=0.069, n=4800))
    s.commit()
    row = s.scalar(select(FactorICDaily))
    assert row.as_of == date(2026, 6, 4) and row.rank_ic == 0.069 and row.n == 4800
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/pytest tests/test_attribution_models.py -v`
Expected: FAIL with `ImportError: cannot import name 'DecisionOutcome'`

- [ ] **Step 3: Write minimal implementation**

Append to `backend/app/db/models.py` (after the existing models; mirror their `Mapped`/`mapped_column` style and the existing imports — `Integer, String, Float, Date, Boolean, ForeignKey, Index` from sqlalchemy):

```python
class DecisionOutcome(Base):
    __tablename__ = "decision_outcomes"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    decision_id: Mapped[int] = mapped_column(ForeignKey("decisions.id"), unique=True)
    code: Mapped[str] = mapped_column(String(16))
    decided_on: Mapped[date] = mapped_column(Date)
    action: Mapped[str] = mapped_column(String(8))
    entry_close: Mapped[float] = mapped_column(Float)
    ret_t1: Mapped[float | None] = mapped_column(Float, nullable=True)
    ret_t3: Mapped[float | None] = mapped_column(Float, nullable=True)
    ret_t5: Mapped[float | None] = mapped_column(Float, nullable=True)
    ret_t10: Mapped[float | None] = mapped_column(Float, nullable=True)
    hit: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    last_updated: Mapped[date] = mapped_column(Date)


Index("ix_decision_outcomes_decided_on", DecisionOutcome.decided_on)


class FactorICDaily(Base):
    __tablename__ = "factor_ic_daily"
    as_of: Mapped[date] = mapped_column(Date, primary_key=True)
    ic: Mapped[float | None] = mapped_column(Float, nullable=True)
    rank_ic: Mapped[float | None] = mapped_column(Float, nullable=True)
    n: Mapped[int] = mapped_column(Integer, default=0)
```

IMPORTANT: `Boolean` is NOT currently imported in models.py (the line is `from sqlalchemy import String, Float, Integer, Date, DateTime, ForeignKey, Index`). You MUST add `Boolean` to that import line, otherwise `DecisionOutcome.hit` fails at import.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/bin/pytest tests/test_attribution_models.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/app/db/models.py backend/tests/test_attribution_models.py
git commit -m "feat(attribution): decision_outcomes + factor_ic_daily models"
```

---

### Task 2: 决策后向收益与命中(纯逻辑 + 回填)

**Files:**
- Create: `backend/app/attribution/__init__.py`
- Create: `backend/app/attribution/outcomes.py`
- Test: `backend/tests/test_attribution_outcomes.py`

**Interfaces:**
- Consumes: `app/screener/filters.forward_return`、`app/data/quote_store.QuoteStore`(`get_bars`/`trading_dates`)、`DecisionOutcome`、`Decision`。
- Produces:
  - `compute_outcome(action: str, closes: list[float]) -> dict` — `closes[0]` = decided_on 当日收盘,`closes[k]` = 之后第 k 个交易日收盘。返回 `{entry_close, ret_t1, ret_t3, ret_t5, ret_t10, hit}`;窗口不足的 horizon 为 None;hit 以 t5 定(BUY: ret_t5>0;SELL: ret_t5<0;ret_t5 为 None 则 hit None)。
  - `backfill_outcomes(session, store, as_of: date, *, lookback_days: int = 15, account_id: int = 1) -> int` — 对 decided_on 在 `[as_of − lookback_days, as_of]` 且 status=="APPROVED" 且 action∈{BUY,SELL} 的决策,用 `store.get_bars(code, decided_on, as_of)` 取 `trade_date >= decided_on` 的收盘序列,`compute_outcome` 后按 `decision_id` upsert `DecisionOutcome`,返回 upsert 行数。
  - `hit_rate(session, *, window: int = 30, as_of: date) -> float | None` — 取 decided_on 在最近 window 天、hit 非 None 的 outcome,返回命中比例(无样本返回 None)。

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_attribution_outcomes.py
from datetime import date, timedelta
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from app.db.database import Base
import app.db.models  # noqa
from app.db.models import Decision, DecisionOutcome, DailyQuote
from app.data.quote_store import QuoteStore
from app.attribution.outcomes import compute_outcome, backfill_outcomes, hit_rate


def _sess():
    e = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(e)
    return sessionmaker(bind=e, future=True)()


def test_compute_outcome_buy_hit():
    closes = [100, 101, 102, 103, 104, 105, 106, 107, 108, 109, 110]  # t0..t10
    out = compute_outcome("BUY", closes)
    assert out["entry_close"] == 100
    assert abs(out["ret_t5"] - 0.05) < 1e-9
    assert out["hit"] is True            # BUY 且 ret_t5>0
    assert out["ret_t10"] is not None


def test_compute_outcome_sell_hit_on_decline():
    closes = [100, 99, 98, 97, 96, 95]   # 只到 t5
    out = compute_outcome("SELL", closes)
    assert out["hit"] is True            # SELL 且 ret_t5<0 = 卖在下跌前
    assert out["ret_t10"] is None        # 窗口不足


def test_compute_outcome_short_window_no_hit():
    out = compute_outcome("BUY", [100, 101])   # 不足 t5
    assert out["ret_t5"] is None and out["hit"] is None


def _seed_quotes(s, code, start: date, closes: list[float]):
    for i, c in enumerate(closes):
        s.add(DailyQuote(code=code, trade_date=start + timedelta(days=i),
                         open=c, high=c, low=c, close=c, vol=1.0))
    s.commit()


def test_backfill_and_hit_rate():
    s = _sess()
    d0 = date(2026, 6, 1)
    _seed_quotes(s, "600519.SH", d0, [100, 101, 102, 103, 104, 105])  # 连续6日
    s.add(Decision(as_of=d0, code="600519.SH", action="BUY", confidence=0.8,
                   shares=100, reasoning="", status="APPROVED", created_at=d0))
    s.add(Decision(as_of=d0, code="000001.SZ", action="HOLD", confidence=0.5,
                   shares=0, reasoning="", status="APPROVED", created_at=d0))  # 不计
    s.commit()
    store = QuoteStore(s)
    n = backfill_outcomes(s, store, date(2026, 6, 6), lookback_days=15)
    assert n == 1                                   # 只回填 BUY
    row = s.scalar(select(DecisionOutcome))
    assert row.code == "600519.SH" and row.hit is True
    assert hit_rate(s, window=30, as_of=date(2026, 6, 6)) == 1.0


def test_backfill_idempotent():
    s = _sess()
    d0 = date(2026, 6, 1)
    _seed_quotes(s, "600519.SH", d0, [100, 101, 102, 103, 104, 105])
    s.add(Decision(as_of=d0, code="600519.SH", action="BUY", confidence=0.8,
                   shares=100, reasoning="", status="APPROVED", created_at=d0))
    s.commit()
    store = QuoteStore(s)
    backfill_outcomes(s, store, date(2026, 6, 6))
    backfill_outcomes(s, store, date(2026, 6, 6))
    assert s.query(DecisionOutcome).count() == 1    # 不累积
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/pytest tests/test_attribution_outcomes.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.attribution'`

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/attribution/__init__.py
```

```python
# backend/app/attribution/outcomes.py
"""决策后向收益与命中:对已执行(APPROVED)的 BUY/SELL,从决策日收盘起算
ret_t1/t3/t5/t10,命中以 t5 定(BUY 涨=命中,SELL 跌=命中)。回填幂等(按 decision_id upsert)。"""
from datetime import date, timedelta
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.screener.filters import forward_return
from app.db.models import Decision, DecisionOutcome

_OFFSETS = {"ret_t1": 1, "ret_t3": 3, "ret_t5": 5, "ret_t10": 10}


def compute_outcome(action: str, closes: list[float]) -> dict:
    entry = closes[0]
    rets = {}
    for field, n in _OFFSETS.items():
        fut = closes[n] if len(closes) > n else None
        rets[field] = forward_return(entry, fut)
    r5 = rets["ret_t5"]
    hit = None
    if r5 is not None:
        hit = (r5 > 0) if action == "BUY" else (r5 < 0)
    return {"entry_close": entry, **rets, "hit": hit}


def backfill_outcomes(session: Session, store, as_of: date, *,
                      lookback_days: int = 15, account_id: int = 1) -> int:
    start = as_of - timedelta(days=lookback_days)
    decisions = session.scalars(select(Decision).where(
        Decision.as_of >= start, Decision.as_of <= as_of,
        Decision.status == "APPROVED",
        Decision.action.in_(("BUY", "SELL")))).all()
    count = 0
    for d in decisions:
        bars = store.get_bars(d.code, d.as_of, as_of)
        closes = [b.close for b in bars if b.trade_date >= d.as_of]
        if not closes:
            continue
        oc = compute_outcome(d.action, closes)
        row = session.scalar(select(DecisionOutcome).where(
            DecisionOutcome.decision_id == d.id))
        if row is None:
            row = DecisionOutcome(decision_id=d.id, code=d.code, decided_on=d.as_of,
                                  action=d.action, entry_close=oc["entry_close"],
                                  last_updated=as_of)
            session.add(row)
        row.entry_close = oc["entry_close"]
        row.ret_t1, row.ret_t3 = oc["ret_t1"], oc["ret_t3"]
        row.ret_t5, row.ret_t10 = oc["ret_t5"], oc["ret_t10"]
        row.hit = oc["hit"]
        row.last_updated = as_of
        count += 1
    session.commit()
    return count


def hit_rate(session: Session, *, window: int = 30, as_of: date) -> float | None:
    start = as_of - timedelta(days=window)
    rows = session.scalars(select(DecisionOutcome).where(
        DecisionOutcome.decided_on >= start,
        DecisionOutcome.hit.is_not(None))).all()
    hits = [r.hit for r in rows]
    return (sum(1 for h in hits if h) / len(hits)) if hits else None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/bin/pytest tests/test_attribution_outcomes.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/app/attribution/__init__.py backend/app/attribution/outcomes.py backend/tests/test_attribution_outcomes.py
git commit -m "feat(attribution): decision forward returns + hit + idempotent backfill"
```

---

### Task 3: 复合因子每日前向 IC(纯逻辑 + 回填)

**Files:**
- Create: `backend/app/attribution/forward_ic.py`
- Test: `backend/tests/test_attribution_forward_ic.py`

**Interfaces:**
- Consumes: `DiscoveryPick`、`FactorICDaily`、`QuoteStore`、`pandas`。
- Produces:
  - `daily_ic(pairs: list[tuple[float, float]]) -> tuple[float | None, float | None, int]` — 输入 (score, fwd_ret) 对,返回 `(ic, rank_ic, n)`;n<2 或任一无方差 → `(None, None, n)`。
  - `backfill_factor_ic(session, store, as_of: date, *, horizon: int = 5, lookback_days: int = 30) -> int` — 对每个 DiscoveryPick 的 pick_date(在 `[as_of − lookback_days, as_of]`)且该日 + horizon 交易日 ≤ 最新数据,取该日各 code 的 `DiscoveryPick.score` 与其 horizon 日前向收益,`daily_ic` 后按 `as_of` upsert `FactorICDaily`,返回 upsert 行数。前向收益用 `store.get_bars(code, pick_date, pick_date+很多天)` 的收盘序列第 horizon 个 vs 第 0 个。
  - `latest_rolling_rank_ic(session, *, as_of: date, window: int = 20) -> float | None` — 最近 window 个 `FactorICDaily` 行的 `rank_ic` 均值(忽略 None),无样本 None。

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_attribution_forward_ic.py
from datetime import date, timedelta
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from app.db.database import Base
import app.db.models  # noqa
from app.db.models import DiscoveryPick, FactorICDaily, DailyQuote
from app.data.quote_store import QuoteStore
from app.attribution.forward_ic import daily_ic, backfill_factor_ic, latest_rolling_rank_ic


def _sess():
    e = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(e)
    return sessionmaker(bind=e, future=True)()


def test_daily_ic_perfect_rank_correlation():
    # score 越高、前向收益越高 → RankIC = 1
    pairs = [(3.0, 0.05), (2.0, 0.03), (1.0, 0.01)]
    ic, ric, n = daily_ic(pairs)
    assert n == 3
    assert abs(ric - 1.0) < 1e-9


def test_daily_ic_no_variance_returns_none():
    ic, ric, n = daily_ic([(1.0, 0.0), (1.0, 0.0)])
    assert ic is None and ric is None


def _seed(s, code, start, closes, score, pick_date):
    for i, c in enumerate(closes):
        s.add(DailyQuote(code=code, trade_date=start + timedelta(days=i),
                         open=c, high=c, low=c, close=c, vol=1.0))
    s.add(DiscoveryPick(as_of=pick_date, code=code, rank=1, score=score, factors="{}"))


def test_backfill_factor_ic_writes_row():
    s = _sess()
    d0 = date(2026, 6, 1)
    # 两只股票,5日后收益与 score 同序 → RankIC 正
    _seed(s, "600519.SH", d0, [100, 100, 100, 100, 100, 110], score=2.0, pick_date=d0)
    _seed(s, "000001.SZ", d0, [50, 50, 50, 50, 50, 51], score=1.0, pick_date=d0)
    s.commit()
    store = QuoteStore(s)
    n = backfill_factor_ic(s, store, date(2026, 6, 7), horizon=5)
    assert n == 1
    row = s.scalar(select(FactorICDaily).where(FactorICDaily.as_of == d0))
    assert row is not None and row.n == 2 and row.rank_ic is not None
    assert latest_rolling_rank_ic(s, as_of=date(2026, 6, 7), window=20) == row.rank_ic
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/pytest tests/test_attribution_forward_ic.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.attribution.forward_ic'`

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/attribution/forward_ic.py
"""复合因子每日前向 IC:对 DiscoveryPick 某日的 score 截面 vs 各 code horizon 日前向收益,
算 IC(Pearson)/RankIC(Spearman),一行一 as_of,按 as_of upsert,回填幂等。"""
from datetime import date, timedelta
import pandas as pd
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from app.db.models import DiscoveryPick, FactorICDaily


def daily_ic(pairs: list[tuple[float, float]]) -> tuple[float | None, float | None, int]:
    df = pd.DataFrame(pairs, columns=["score", "ret"]).dropna()
    n = len(df)
    if n < 2 or df["score"].nunique() < 2 or df["ret"].nunique() < 2:
        return (None, None, n)
    ic = float(df["score"].corr(df["ret"]))
    ric = float(df["score"].corr(df["ret"], method="spearman"))
    return (ic, ric, n)


def _fwd_return(store, code: str, pick_date: date, horizon: int) -> float | None:
    bars = store.get_bars(code, pick_date, pick_date + timedelta(days=horizon * 4 + 10))
    closes = [b.close for b in bars if b.trade_date >= pick_date]
    if len(closes) <= horizon or closes[0] == 0:
        return None
    return closes[horizon] / closes[0] - 1.0


def backfill_factor_ic(session: Session, store, as_of: date, *, horizon: int = 5,
                       lookback_days: int = 30) -> int:
    start = as_of - timedelta(days=lookback_days)
    pick_dates = session.scalars(select(DiscoveryPick.as_of).where(
        DiscoveryPick.as_of >= start, DiscoveryPick.as_of <= as_of).distinct()).all()
    count = 0
    for pdate in sorted(set(pick_dates)):       # 不要用 pd:会遮蔽 pandas 别名
        picks = session.scalars(select(DiscoveryPick).where(
            DiscoveryPick.as_of == pdate)).all()
        pairs = []
        for p in picks:
            r = _fwd_return(store, p.code, pdate, horizon)
            if r is not None:
                pairs.append((p.score, r))
        if len(pairs) < 2:
            continue                       # 前向窗口未走完 / 数据不足,暂不写
        ic, ric, n = daily_ic(pairs)
        row = session.get(FactorICDaily, pdate)
        if row is None:
            row = FactorICDaily(as_of=pdate)
            session.add(row)
        row.ic, row.rank_ic, row.n = ic, ric, n
        count += 1
    session.commit()
    return count


def latest_rolling_rank_ic(session: Session, *, as_of: date,
                           window: int = 20) -> float | None:
    rows = session.scalars(select(FactorICDaily).where(
        FactorICDaily.as_of <= as_of).order_by(
        FactorICDaily.as_of.desc()).limit(window)).all()
    vals = [r.rank_ic for r in rows if r.rank_ic is not None]
    return (sum(vals) / len(vals)) if vals else None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/bin/pytest tests/test_attribution_forward_ic.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/app/attribution/forward_ic.py backend/tests/test_attribution_forward_ic.py
git commit -m "feat(attribution): daily forward IC/RankIC + idempotent backfill + rolling mean"
```

---

### Task 4: 权益回撤与滚动胜率(纯逻辑)

**Files:**
- Create: `backend/app/attribution/equity.py`
- Test: `backend/tests/test_attribution_equity.py`

**Interfaces:**
- Produces:
  - `current_drawdown(totals: list[float]) -> float | None` — 给定按时间升序的权益 total 序列,返回当前对历史峰值的回撤(≤0);空列表 None。
  - `rolling_hit_rate(hits: list[bool | None]) -> float | None` — 忽略 None,返回命中比例;无有效样本 None。

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_attribution_equity.py
from app.attribution.equity import current_drawdown, rolling_hit_rate


def test_drawdown_from_peak():
    # 峰值 120,末值 102 → -15%
    assert abs(current_drawdown([100, 120, 110, 102]) - (-0.15)) < 1e-9


def test_drawdown_new_high_zero():
    assert current_drawdown([100, 110, 130]) == 0.0


def test_drawdown_empty_none():
    assert current_drawdown([]) is None


def test_rolling_hit_rate_ignores_none():
    assert rolling_hit_rate([True, False, None, True]) == 2 / 3


def test_rolling_hit_rate_no_sample_none():
    assert rolling_hit_rate([None, None]) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/pytest tests/test_attribution_equity.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.attribution.equity'`

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/attribution/equity.py
"""权益回撤与滚动胜率(纯计算,无 DB)。供日报与 Phase 3b 策略闸读取。"""


def current_drawdown(totals: list[float]) -> float | None:
    if not totals:
        return None
    peak = totals[0]
    dd = 0.0
    for t in totals:
        peak = max(peak, t)
        if peak:
            dd = min(dd, t / peak - 1.0)
    return dd


def rolling_hit_rate(hits: list[bool | None]) -> float | None:
    valid = [h for h in hits if h is not None]
    return (sum(1 for h in valid if h) / len(valid)) if valid else None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/bin/pytest tests/test_attribution_equity.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/app/attribution/equity.py backend/tests/test_attribution_equity.py
git commit -m "feat(attribution): pure drawdown + rolling hit-rate helpers"
```

---

### Task 5: 接入 daily_full(step_attribution)+ 日报扩展

**Files:**
- Modify: `backend/scripts/daily_full.py`
- Modify: `backend/app/reporting/daily_summary.py`
- Test: `backend/tests/test_daily_full_phase3.py`
- Test: `backend/tests/test_daily_summary_attribution.py`

**Interfaces:**
- Consumes: Task 2 `backfill_outcomes`/`hit_rate`、Task 3 `backfill_factor_ic`/`latest_rolling_rank_ic`、Task 4 `current_drawdown`。
- Produces:
  - `daily_full.step_attribution()` — `backfill_outcomes(session, store, as_of)` + `backfill_factor_ic(session, store, as_of)`;追加进 `run_all` 步骤元组末尾(在 `step_mark` 之后)。
  - `daily_summary.build_daily_summary(...)` 追加两行:近30日决策胜率(`hit_rate`)与最新20日滚动前向 RankIC(`latest_rolling_rank_ic`),无数据显示 N/A。签名不变。

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_daily_full_phase3.py
import scripts.daily_full as df


def test_run_all_appends_step_attribution(monkeypatch):
    calls = []
    for name in ("step_quotes", "step_qlib", "step_tracklist",
                 "step_select", "step_debate", "step_mark", "step_attribution"):
        monkeypatch.setattr(df, name, (lambda n=name: lambda: calls.append(n))())
    df.run_all()
    assert calls[-1] == "step_attribution"
    assert calls == ["step_quotes", "step_qlib", "step_tracklist",
                     "step_select", "step_debate", "step_mark", "step_attribution"]
```

```python
# backend/tests/test_daily_summary_attribution.py
from datetime import date
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.db.database import Base
import app.db.models  # noqa
from app.db.models import Account, DecisionOutcome, FactorICDaily
from app.reporting.daily_summary import build_daily_summary


def _sess():
    e = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                      poolclass=StaticPool, future=True)
    Base.metadata.create_all(e)
    s = sessionmaker(bind=e, future=True)()
    s.add(Account(id=1, name="main", cash=500_000.0)); s.commit()
    return s


def test_summary_includes_hitrate_and_ic():
    s = _sess()
    d = date(2026, 6, 12)
    s.add(DecisionOutcome(decision_id=1, code="600519.SH", decided_on=date(2026, 6, 4),
                          action="BUY", entry_close=100.0, ret_t5=0.05, hit=True,
                          last_updated=d))
    s.add(FactorICDaily(as_of=date(2026, 6, 4), ic=0.02, rank_ic=0.07, n=4000))
    s.commit()
    text = build_daily_summary(s, d, account_id=1)
    assert "胜率" in text
    assert "RankIC" in text or "IC" in text


def test_summary_attribution_na_when_empty():
    s = _sess()
    text = build_daily_summary(s, date(2026, 6, 12), account_id=1)
    assert "胜率 N/A" in text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/pytest tests/test_daily_full_phase3.py tests/test_daily_summary_attribution.py -v`
Expected: FAIL (`step_attribution` 不存在 / 摘要无"胜率")

- [ ] **Step 3: Write minimal implementation**

In `backend/scripts/daily_full.py`, add the step function (after `step_mark`):

```python
def step_attribution() -> None:
    from app.attribution.outcomes import backfill_outcomes
    from app.attribution.forward_ic import backfill_factor_ic
    session = _session()
    store = QuoteStore(session)
    as_of = store.trading_dates(date.today(), 1)[0]
    backfill_outcomes(session, store, as_of)
    backfill_factor_ic(session, store, as_of)
```

Extend the `run_all` step tuple:

```python
    for step in (step_quotes, step_qlib, step_tracklist,
                 step_select, step_debate, step_mark, step_attribution):
```

In `backend/app/reporting/daily_summary.py`, add attribution lines. Add imports at top:

```python
from app.attribution.outcomes import hit_rate
from app.attribution.forward_ic import latest_rolling_rank_ic
```

Before the final `return "\n".join(lines)`, insert:

```python
    hr = hit_rate(session, window=30, as_of=as_of)
    ric = latest_rolling_rank_ic(session, as_of=as_of, window=20)
    lines.append(f"近30日胜率 {hr*100:.0f}%" if hr is not None else "近30日胜率 N/A")
    lines.append(f"滚动RankIC {ric:+.4f}" if ric is not None else "滚动RankIC N/A")
```

(Note: the empty-summary test asserts the substring `"胜率 N/A"` — `"近30日胜率 N/A"` contains it, so it passes.)

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/bin/pytest tests/test_daily_full_phase3.py tests/test_daily_summary_attribution.py tests/test_daily_summary.py tests/test_daily_full_phase2.py -v`
Expected: PASS (new phase3 tests + the existing daily_summary / phase2 order tests still green)

- [ ] **Step 5: Commit**

```bash
git add backend/scripts/daily_full.py backend/app/reporting/daily_summary.py backend/tests/test_daily_full_phase3.py backend/tests/test_daily_summary_attribution.py
git commit -m "feat(daily): step_attribution + hit-rate/forward-IC in daily summary"
```

---

### Task 6: 全后端回归 + 归因集成冒烟

**Files:**
- Test: `backend/tests/test_attribution_integration.py`

**Interfaces:**
- Consumes: Task 2/3 回填函数;真实 DB(已有 DiscoveryPick/Decision 历史)。

- [ ] **Step 1: Write the integration test**

```python
# backend/tests/test_attribution_integration.py
import pytest
from datetime import date
from app.db.database import make_engine, make_session_factory
import app.db.models  # noqa
from app.data.quote_store import QuoteStore
from app.attribution.outcomes import backfill_outcomes
from app.attribution.forward_ic import backfill_factor_ic

pytestmark = pytest.mark.integration


def test_attribution_backfill_runs_on_real_db():
    session = make_session_factory(make_engine())()
    store = QuoteStore(session)
    as_of = store.trading_dates(date.today(), 1)[0]
    # 真实库上回填不应抛错;行数 >= 0
    n_oc = backfill_outcomes(session, store, as_of)
    n_ic = backfill_factor_ic(session, store, as_of)
    assert n_oc >= 0 and n_ic >= 0
```

- [ ] **Step 2: Run integration + full suite**

Run: `cd backend && .venv/bin/pytest tests/test_attribution_integration.py -v -m integration`
Expected: PASS(真实库可连时);否则按环境 SKIP/ERROR 由执行者判断
Run: `cd backend && .venv/bin/pytest -q`
Expected: 全绿(新增归因测试 + 既有全套无回归)

- [ ] **Step 3: Commit**

```bash
git add backend/tests/test_attribution_integration.py
git commit -m "test(attribution): integration backfill on real db + full regression"
```

---

## Self-Review

**Spec coverage(对照 spec §7.1 attribution):**
- §7.1 outcomes.py → decision_outcomes:决策后向收益+胜率 → Task 1(表)+ Task 2 ✓
- §7.1 forward_ic.py → factor_ic_daily:每日 IC/RankIC 时序 → Task 1(表)+ Task 3 ✓
- §7.1 equity.py:回撤+(超额留 3b)→ Task 4(回撤+滚动胜率纯函数)✓
- §7.4 验收(胜率/前向IC 可查)→ Task 5 日报 + Task 6 集成 ✓
- 接入每日链 → Task 5 step_attribution ✓
- 注:§7.1 提到"对沪深300超额"——本 Phase 3a 暂只做策略自身回撤;超额(需基准序列)留到 3b 风控规则或后续,Self-review 记为有意缩减(见下"范围说明")。

**范围说明:** 本计划是 Phase 3 的前半(归因度量层)。Phase 3b(策略闸 policy + 三个自动动作 + guardrails)是独立后续计划,读取本层的 `hit_rate`/`latest_rolling_rank_ic`/`current_drawdown` 及持仓在 DiscoveryPick 的排名。"对沪深300超额回撤"并入 3b 的风控规则一并实现(那里才需要基准比较)。

**Placeholder scan:** 无 TBD/TODO;每代码步含完整代码与预期输出。

**Type consistency:**
- `compute_outcome(action, closes) -> dict`(键 entry_close/ret_t1/t3/t5/t10/hit)Task 2 定义,backfill_outcomes 内部使用一致。
- `backfill_outcomes(session, store, as_of, *, lookback_days, account_id)`、`hit_rate(session, *, window, as_of)` Task 2 定义,Task 5 调用一致(hit_rate 用 window=30)。
- `daily_ic(pairs)->(ic,rank_ic,n)`、`backfill_factor_ic(session, store, as_of, *, horizon, lookback_days)`、`latest_rolling_rank_ic(session, *, as_of, window)` Task 3 定义,Task 5 调用一致(window=20)。
- `current_drawdown(totals)`、`rolling_hit_rate(hits)` Task 4 定义(注:daily_summary 用 hit_rate(DB聚合)而非 rolling_hit_rate;rolling_hit_rate 供 3b 用纯列表)。
- 新模型 `DecisionOutcome`/`FactorICDaily` 字段 Task 1 定义,Task 2/3/5 引用一致。

**执行前需核对(给实现者):**
1. 已核实:`app/db/models.py` 当前导入为 `from sqlalchemy import String, Float, Integer, Date, DateTime, ForeignKey, Index`,**不含 Boolean** → Task 1 必须加 `Boolean`。
1b. 已核实:`forward_ic.py` 回填循环变量用 `pdate`(不可用 `pd`,会遮蔽 `import pandas as pd`)。
2. `Decision.action.in_((...))` 与 `DecisionOutcome.hit.is_not(None)` 是 SQLAlchemy 2.x 用法,项目已用 2.x(`Mapped`/`mapped_column`),可用。
3. daily_summary.py 的 `as_of` 形参在函数内可用(Task 5 追加行引用 `as_of`/`session`,均为现有形参)。
