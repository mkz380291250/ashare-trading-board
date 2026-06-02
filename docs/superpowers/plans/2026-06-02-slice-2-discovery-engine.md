# Slice 2: Discovery Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A daily opportunity-discovery engine that scores the whole A-share market on price/volume momentum and persists the Top-8 候选 ("机会榜"), reading from the existing historical quote DB (no tushare at scan time).

**Architecture:** New `backend/app/discovery/` module, parallel to `data/`/`trading/`. A pluggable `SignalProvider` (first impl `MomentumProvider`, 4 factors) consumes a `MarketSnapshot` built by a `MarketHistory` that reads `QuoteStore` (the historical DB). A `DiscoveryScorer` percentile-normalizes each factor, weighted-sums, and truncates to Top-8. A `DiscoveryRunner` persists `discovery_picks`. REST endpoint + dashboard panel surface results.

**Tech Stack:** Python 3.11, SQLAlchemy 2.x, pandas, pytest; React+Vite+TS. Reuses `app/data/quote_store.py::QuoteStore`, `DailyQuote`.

---

## Reference: Spec

`docs/superpowers/specs/2026-06-02-slice-2-discovery-engine-design.md`. Factors:
mom_5d (5d return), turnover (turnover_rate), vol_ratio (volume_ratio), breakout
(close / 20d-high). Percentile-normalize → equal-weight sum → Top-8. **Adaptation:**
the historical DB now exists, so `MarketHistory` reads `QuoteStore`, not tushare.

## File Structure

```
backend/
  app/
    discovery/
      __init__.py
      snapshot.py     # NEW: StockData dataclass, MarketHistory ABC, QuoteStoreMarketHistory
      providers.py    # NEW: SignalProvider ABC, MomentumProvider (4 factors)
      scorer.py       # NEW: percentile_rank, DiscoveryScorer (weighted sum -> Top-N)
      runner.py       # NEW: DiscoveryRunner (provider+scorer -> persist)
    data/quote_store.py   # MODIFY: add get_range, trading_dates
    db/models.py          # MODIFY: add DiscoveryPick
    api/routes_discovery.py  # NEW: GET /api/discovery
    main.py               # MODIFY: include discovery router
  scripts/run_discovery.py  # NEW
  tests/
    test_discovery_models.py
    test_momentum_provider.py
    test_discovery_scorer.py
    test_market_history.py
    test_discovery_runner.py
    test_api_discovery.py
frontend/src/components/DiscoveryPanel.tsx   # NEW
frontend/src/pages/Dashboard.tsx             # MODIFY
```

---

## Task 1: DiscoveryPick model

**Files:**
- Modify: `backend/app/db/models.py`
- Test: `backend/tests/test_discovery_models.py`

- [ ] **Step 1: Write failing test `backend/tests/test_discovery_models.py`**

```python
from datetime import date
from app.db.models import DiscoveryPick


def test_discovery_pick_roundtrip(session):
    p = DiscoveryPick(as_of=date(2026, 5, 29), code="600519.SH", rank=1,
                      score=0.95, factors='{"mom_5d": 0.1}')
    session.add(p); session.commit()
    got = session.query(DiscoveryPick).one()
    assert got.code == "600519.SH" and got.rank == 1
    assert got.score == 0.95 and got.as_of == date(2026, 5, 29)
```

- [ ] **Step 2: Run test, expect failure**

Run (from `backend/`): `.venv/bin/python -m pytest tests/test_discovery_models.py -v`
Expected: FAIL — `ImportError: cannot import name 'DiscoveryPick'`.

- [ ] **Step 3: Append to `backend/app/db/models.py`**

```python
class DiscoveryPick(Base):
    __tablename__ = "discovery_picks"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    as_of: Mapped[date] = mapped_column(Date)
    code: Mapped[str] = mapped_column(String(16))
    rank: Mapped[int] = mapped_column(Integer)
    score: Mapped[float] = mapped_column(Float)
    factors: Mapped[str] = mapped_column(String, default="{}")  # JSON text


Index("ix_discovery_picks_as_of", DiscoveryPick.as_of)
```

(`Index`, `Integer`, `Date`, `String`, `Float`, `Mapped`, `mapped_column` are already imported in this file.)

- [ ] **Step 4: Run test, expect pass**

Run: `.venv/bin/python -m pytest tests/test_discovery_models.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/db/models.py backend/tests/test_discovery_models.py
git commit -m "feat(discovery): DiscoveryPick model for the 机会榜 Top-8"
```

---

## Task 2: MarketSnapshot StockData + MomentumProvider

**Files:**
- Create: `backend/app/discovery/__init__.py`, `backend/app/discovery/snapshot.py` (StockData only here), `backend/app/discovery/providers.py`
- Test: `backend/tests/test_momentum_provider.py`

`StockData` is a per-stock trailing window. `MomentumProvider.compute(snapshot)`
returns `{factor_name: {code: raw_value}}` for the 4 factors, including only codes
with enough data.

- [ ] **Step 1: Write failing test `backend/tests/test_momentum_provider.py`**

```python
from app.discovery.snapshot import StockData
from app.discovery.providers import MomentumProvider


def _stock(code, closes, highs, turnover, vol_ratio):
    return StockData(code=code, closes=closes, highs=highs,
                     turnover=turnover, vol_ratio=vol_ratio)


def test_momentum_factors():
    # 6 closes so mom_5d = closes[-1]/closes[-6]-1 = 12/10-1 = 0.2
    closes = [10.0, 10.5, 11.0, 11.2, 11.8, 12.0]
    highs = [10.0, 10.5, 11.0, 11.2, 11.8, 12.5]  # 20d-high = 12.5; breakout = 12/12.5
    snap = {"A": _stock("A", closes, highs, turnover=3.0, vol_ratio=1.5)}
    out = MomentumProvider().compute(snap)
    assert set(out.keys()) == {"mom_5d", "turnover", "vol_ratio", "breakout"}
    assert abs(out["mom_5d"]["A"] - 0.2) < 1e-9
    assert out["turnover"]["A"] == 3.0
    assert out["vol_ratio"]["A"] == 1.5
    assert abs(out["breakout"]["A"] - (12.0 / 12.5)) < 1e-9


def test_skips_codes_with_insufficient_history():
    snap = {"B": _stock("B", [10.0, 11.0], [10.0, 11.0], 2.0, 1.0)}  # <6 closes
    out = MomentumProvider().compute(snap)
    assert out["mom_5d"] == {}        # no mom_5d for B
    # turnover/vol_ratio still available since they don't need history
    assert out["turnover"]["B"] == 2.0


def test_skips_none_metrics():
    closes = [10.0, 10.5, 11.0, 11.2, 11.8, 12.0]
    snap = {"C": StockData("C", closes, closes, turnover=None, vol_ratio=None)}
    out = MomentumProvider().compute(snap)
    assert "C" not in out["turnover"] and "C" not in out["vol_ratio"]
    assert "C" in out["mom_5d"]
```

- [ ] **Step 2: Run test, expect failure**

Run: `.venv/bin/python -m pytest tests/test_momentum_provider.py -v`
Expected: FAIL — modules missing.

- [ ] **Step 3: Write `backend/app/discovery/snapshot.py`**

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class StockData:
    code: str
    closes: list[float]   # ascending, ending on as_of
    highs: list[float]    # ascending, ending on as_of
    turnover: float | None
    vol_ratio: float | None


class MarketHistory(ABC):
    @abstractmethod
    def load(self, as_of: date, window: int = 20) -> dict[str, StockData]:
        ...
```

Create empty `backend/app/discovery/__init__.py`.

- [ ] **Step 4: Write `backend/app/discovery/providers.py`**

```python
from abc import ABC, abstractmethod
from app.discovery.snapshot import StockData


class SignalProvider(ABC):
    @abstractmethod
    def compute(self, snapshot: dict[str, StockData]) -> dict[str, dict[str, float]]:
        """Return {factor_name: {code: raw_value}}."""
        ...


class MomentumProvider(SignalProvider):
    HIGH_LOOKBACK = 20

    def compute(self, snapshot: dict[str, StockData]) -> dict[str, dict[str, float]]:
        out = {"mom_5d": {}, "turnover": {}, "vol_ratio": {}, "breakout": {}}
        for code, s in snapshot.items():
            if len(s.closes) >= 6 and s.closes[-6] != 0:
                out["mom_5d"][code] = s.closes[-1] / s.closes[-6] - 1.0
            if s.closes and s.highs:
                hi = max(s.highs[-self.HIGH_LOOKBACK:])
                if hi != 0:
                    out["breakout"][code] = s.closes[-1] / hi
            if s.turnover is not None:
                out["turnover"][code] = s.turnover
            if s.vol_ratio is not None:
                out["vol_ratio"][code] = s.vol_ratio
        return out
```

- [ ] **Step 5: Run test, expect pass**

Run: `.venv/bin/python -m pytest tests/test_momentum_provider.py -v`
Expected: PASS (3 tests).

- [ ] **Step 6: Commit**

```bash
git add backend/app/discovery/__init__.py backend/app/discovery/snapshot.py backend/app/discovery/providers.py backend/tests/test_momentum_provider.py
git commit -m "feat(discovery): StockData/MarketHistory + MomentumProvider (4 factors)"
```

---

## Task 3: DiscoveryScorer

**Files:**
- Create: `backend/app/discovery/scorer.py`
- Test: `backend/tests/test_discovery_scorer.py`

Percentile-normalize each factor (average rank, ties share mean percentile),
weighted-sum over factors a code has, sort desc, Top-N. A code is scored only if
it appears in **every** factor map (full coverage).

- [ ] **Step 1: Write failing test `backend/tests/test_discovery_scorer.py`**

```python
from app.discovery.scorer import percentile_rank, DiscoveryScorer


def test_percentile_rank_handles_ties():
    pr = percentile_rank({"a": 10.0, "b": 20.0, "c": 20.0, "d": 30.0})
    assert pr["a"] == 0.25
    assert abs(pr["b"] - 0.625) < 1e-9 and abs(pr["c"] - 0.625) < 1e-9
    assert pr["d"] == 1.0


def test_scorer_ranks_and_truncates():
    factors = {
        "f1": {"a": 1.0, "b": 2.0, "c": 3.0},
        "f2": {"a": 3.0, "b": 2.0, "c": 1.0},
    }
    # equal weights: a -> (0.333+1)/2, c -> (1+0.333)/2 tie; b -> (0.667+0.667)/2
    picks = DiscoveryScorer(top_n=2).score(factors)
    assert len(picks) == 2
    codes = [p[0] for p in picks]
    assert "b" not in codes  # b is the middle, a and c tie higher
    # each pick is (code, score, raw_factors)
    assert picks[0][2] in ({"f1": 1.0, "f2": 3.0}, {"f1": 3.0, "f2": 1.0})


def test_scorer_requires_full_coverage():
    factors = {"f1": {"a": 1.0, "b": 2.0}, "f2": {"a": 5.0}}  # b missing f2
    picks = DiscoveryScorer(top_n=8).score(factors)
    assert [p[0] for p in picks] == ["a"]  # only a has all factors


def test_scorer_weights():
    factors = {"f1": {"a": 1.0, "b": 2.0}, "f2": {"a": 2.0, "b": 1.0}}
    picks = DiscoveryScorer(top_n=2, weights={"f1": 1.0, "f2": 0.0}).score(factors)
    assert picks[0][0] == "b"  # f1 dominant, b higher on f1
```

- [ ] **Step 2: Run test, expect failure**

Run: `.venv/bin/python -m pytest tests/test_discovery_scorer.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Write `backend/app/discovery/scorer.py`**

```python
import pandas as pd


def percentile_rank(values: dict[str, float]) -> dict[str, float]:
    if not values:
        return {}
    s = pd.Series(values)
    ranked = s.rank(pct=True, method="average")
    return {k: float(v) for k, v in ranked.items()}


class DiscoveryScorer:
    def __init__(self, top_n: int = 8, weights: dict[str, float] | None = None):
        self.top_n = top_n
        self.weights = weights

    def score(self, factors: dict[str, dict[str, float]]):
        """factors: {factor_name: {code: raw}}. Returns sorted list of
        (code, total_score, {factor: raw}) truncated to top_n."""
        if not factors:
            return []
        names = list(factors.keys())
        weights = self.weights or {n: 1.0 / len(names) for n in names}
        pct = {n: percentile_rank(factors[n]) for n in names}
        # codes present in EVERY factor
        common = set(factors[names[0]])
        for n in names[1:]:
            common &= set(factors[n])
        scored = []
        for code in common:
            total = sum(weights.get(n, 0.0) * pct[n][code] for n in names)
            raw = {n: factors[n][code] for n in names}
            scored.append((code, total, raw))
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[: self.top_n]
```

- [ ] **Step 4: Run test, expect pass**

Run: `.venv/bin/python -m pytest tests/test_discovery_scorer.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/app/discovery/scorer.py backend/tests/test_discovery_scorer.py
git commit -m "feat(discovery): DiscoveryScorer (percentile normalize, weighted sum, Top-N)"
```

---

## Task 4: QuoteStore reads + QuoteStoreMarketHistory

**Files:**
- Modify: `backend/app/data/quote_store.py` (add `get_range`, `trading_dates`)
- Modify: `backend/app/discovery/snapshot.py` (add `QuoteStoreMarketHistory`)
- Test: `backend/tests/test_market_history.py`

- [ ] **Step 1: Write failing test `backend/tests/test_market_history.py`**

```python
from datetime import date
from app.data.quote_store import QuoteStore
from app.discovery.snapshot import QuoteStoreMarketHistory


def _row(code, d, close, high, turnover=1.0, vol_ratio=1.0):
    return {"code": code, "trade_date": d, "open": close, "high": high,
            "low": close, "close": close, "pre_close": close, "vol": 100.0,
            "amount": 1.0, "adj_factor": 1.0, "turnover_rate": turnover,
            "volume_ratio": vol_ratio, "circ_mv": 1.0, "total_mv": 1.0,
            "pe": 1.0, "pb": 1.0}


def test_history_builds_per_code_window(session):
    qs = QuoteStore(session)
    for i, d in enumerate([date(2026, 1, 2), date(2026, 1, 3), date(2026, 1, 6)]):
        qs.upsert_day(d, [_row("A", d, 10.0 + i, 11.0 + i, turnover=2.0, vol_ratio=1.5)])
    hist = QuoteStoreMarketHistory(qs).load(date(2026, 1, 6), window=20)
    a = hist["A"]
    assert a.closes == [10.0, 11.0, 12.0]   # ascending up to as_of
    assert a.highs == [11.0, 12.0, 13.0]
    assert a.turnover == 2.0 and a.vol_ratio == 1.5  # from the as_of row


def test_history_only_includes_codes_present_on_as_of(session):
    qs = QuoteStore(session)
    qs.upsert_day(date(2026, 1, 2), [_row("B", date(2026, 1, 2), 5.0, 5.0)])  # not on as_of
    qs.upsert_day(date(2026, 1, 6), [_row("A", date(2026, 1, 6), 9.0, 9.0)])
    hist = QuoteStoreMarketHistory(qs).load(date(2026, 1, 6), window=20)
    assert set(hist.keys()) == {"A"}
```

- [ ] **Step 2: Run test, expect failure**

Run: `.venv/bin/python -m pytest tests/test_market_history.py -v`
Expected: FAIL — `get_range`/`QuoteStoreMarketHistory` missing.

- [ ] **Step 3: Add methods to `backend/app/data/quote_store.py`**

Add these methods inside the `QuoteStore` class (after `get_market_on`):

```python
    def trading_dates(self, end: date, limit: int) -> list[date]:
        rows = self.s.scalars(
            select(DailyQuote.trade_date).where(DailyQuote.trade_date <= end)
            .distinct().order_by(DailyQuote.trade_date.desc()).limit(limit)
        ).all()
        return sorted(rows)

    def get_range(self, start: date, end: date) -> list[DailyQuote]:
        return list(self.s.scalars(
            select(DailyQuote).where(
                DailyQuote.trade_date >= start, DailyQuote.trade_date <= end
            ).order_by(DailyQuote.code, DailyQuote.trade_date)
        ).all())
```

- [ ] **Step 4: Add `QuoteStoreMarketHistory` to `backend/app/discovery/snapshot.py`**

Append (it needs `StockData`, `MarketHistory` defined above in the same file):

```python
class QuoteStoreMarketHistory(MarketHistory):
    def __init__(self, store):
        self.store = store

    def load(self, as_of: date, window: int = 20) -> dict[str, StockData]:
        dates = self.store.trading_dates(as_of, window)
        if not dates or dates[-1] != as_of:
            return {}
        rows = self.store.get_range(dates[0], as_of)
        by_code: dict[str, list] = {}
        for r in rows:
            by_code.setdefault(r.code, []).append(r)
        out: dict[str, StockData] = {}
        for code, rs in by_code.items():
            rs.sort(key=lambda r: r.trade_date)
            if rs[-1].trade_date != as_of:
                continue  # not trading on as_of
            out[code] = StockData(
                code=code,
                closes=[r.close for r in rs],
                highs=[r.high for r in rs],
                turnover=rs[-1].turnover_rate,
                vol_ratio=rs[-1].volume_ratio,
            )
        return out
```

- [ ] **Step 5: Run test, expect pass**

Run: `.venv/bin/python -m pytest tests/test_market_history.py -v`
Expected: PASS (2 tests).

- [ ] **Step 6: Commit**

```bash
git add backend/app/data/quote_store.py backend/app/discovery/snapshot.py backend/tests/test_market_history.py
git commit -m "feat(discovery): QuoteStore get_range/trading_dates + QuoteStoreMarketHistory"
```

---

## Task 5: DiscoveryRunner

**Files:**
- Create: `backend/app/discovery/runner.py`
- Test: `backend/tests/test_discovery_runner.py`

Orchestrates: history.load → providers.compute (merge factor maps) → scorer.score
→ upsert `discovery_picks` (replace any existing rows for that as_of, so reruns are
idempotent).

- [ ] **Step 1: Write failing test `backend/tests/test_discovery_runner.py`**

```python
import json
from datetime import date
from app.db.models import DiscoveryPick
from app.discovery.snapshot import StockData, MarketHistory
from app.discovery.providers import MomentumProvider
from app.discovery.scorer import DiscoveryScorer
from app.discovery.runner import DiscoveryRunner


class FakeHistory(MarketHistory):
    def load(self, as_of, window=20):
        def s(code, base):
            closes = [base + i for i in range(6)]
            return StockData(code, closes, closes, turnover=base, vol_ratio=base / 10)
        return {c: s(c, b) for c, b in [("A", 10), ("B", 20), ("C", 30)]}


def test_runner_persists_topn(session):
    runner = DiscoveryRunner(session, FakeHistory(), [MomentumProvider()],
                             DiscoveryScorer(top_n=2))
    picks = runner.run(date(2026, 5, 29))
    assert len(picks) == 2
    rows = session.query(DiscoveryPick).order_by(DiscoveryPick.rank).all()
    assert len(rows) == 2
    assert rows[0].rank == 1 and rows[1].rank == 2
    assert rows[0].score >= rows[1].score
    assert "mom_5d" in json.loads(rows[0].factors)


def test_runner_is_idempotent_per_date(session):
    runner = DiscoveryRunner(session, FakeHistory(), [MomentumProvider()],
                             DiscoveryScorer(top_n=2))
    runner.run(date(2026, 5, 29))
    runner.run(date(2026, 5, 29))  # rerun same date
    assert session.query(DiscoveryPick).count() == 2  # not 4
```

- [ ] **Step 2: Run test, expect failure**

Run: `.venv/bin/python -m pytest tests/test_discovery_runner.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Write `backend/app/discovery/runner.py`**

```python
import json
from datetime import date
from sqlalchemy import delete
from sqlalchemy.orm import Session
from app.db.models import DiscoveryPick
from app.discovery.snapshot import MarketHistory
from app.discovery.providers import SignalProvider
from app.discovery.scorer import DiscoveryScorer


class DiscoveryRunner:
    def __init__(self, session: Session, history: MarketHistory,
                 providers: list[SignalProvider], scorer: DiscoveryScorer,
                 window: int = 20):
        self.s = session
        self.history = history
        self.providers = providers
        self.scorer = scorer
        self.window = window

    def run(self, as_of: date):
        snapshot = self.history.load(as_of, self.window)
        factors: dict[str, dict[str, float]] = {}
        for p in self.providers:
            for name, fmap in p.compute(snapshot).items():
                factors[name] = fmap
        picks = self.scorer.score(factors)
        self.s.execute(delete(DiscoveryPick).where(DiscoveryPick.as_of == as_of))
        for i, (code, total, raw) in enumerate(picks, 1):
            self.s.add(DiscoveryPick(as_of=as_of, code=code, rank=i,
                                     score=total, factors=json.dumps(raw)))
        self.s.commit()
        return picks
```

- [ ] **Step 4: Run test, expect pass**

Run: `.venv/bin/python -m pytest tests/test_discovery_runner.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/app/discovery/runner.py backend/tests/test_discovery_runner.py
git commit -m "feat(discovery): DiscoveryRunner (compute -> score -> persist, idempotent)"
```

---

## Task 6: GET /api/discovery

**Files:**
- Create: `backend/app/api/routes_discovery.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_api_discovery.py`

- [ ] **Step 1: Write failing test `backend/tests/test_api_discovery.py`**

```python
from datetime import date
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.db.database import Base
import app.db.models  # noqa
from app.db.models import DiscoveryPick
from app.main import create_app
from app.api.deps import get_session


def _client():
    engine = create_engine("sqlite:///:memory:", future=True,
                           connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, expire_on_commit=False, future=True)()
    s.add(DiscoveryPick(as_of=date(2026, 5, 28), code="OLD.SH", rank=1, score=0.5, factors="{}"))
    s.add(DiscoveryPick(as_of=date(2026, 5, 29), code="NEW.SH", rank=1, score=0.9,
                        factors='{"mom_5d": 0.2}'))
    s.commit()
    app = create_app()
    app.dependency_overrides[get_session] = lambda: s
    return TestClient(app)


def test_latest_batch():
    r = _client().get("/api/discovery")
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 1 and data[0]["code"] == "NEW.SH"  # only the most recent as_of
    assert data[0]["factors"]["mom_5d"] == 0.2


def test_historical_date():
    r = _client().get("/api/discovery?date=2026-05-28")
    assert r.status_code == 200
    assert r.json()[0]["code"] == "OLD.SH"
```

- [ ] **Step 2: Run test, expect failure**

Run: `.venv/bin/python -m pytest tests/test_api_discovery.py -v`
Expected: FAIL — route missing.

- [ ] **Step 3: Write `backend/app/api/routes_discovery.py`**

```python
import json
from datetime import date
from fastapi import APIRouter, Depends
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from app.api.deps import get_session
from app.db.models import DiscoveryPick

router = APIRouter(prefix="/api", tags=["discovery"])


@router.get("/discovery")
def discovery(date: date | None = None, s: Session = Depends(get_session)):
    target = date
    if target is None:
        target = s.scalar(select(func.max(DiscoveryPick.as_of)))
    if target is None:
        return []
    rows = s.scalars(
        select(DiscoveryPick).where(DiscoveryPick.as_of == target)
        .order_by(DiscoveryPick.rank)
    ).all()
    return [{"as_of": r.as_of.isoformat(), "code": r.code, "rank": r.rank,
             "score": r.score, "factors": json.loads(r.factors or "{}")} for r in rows]
```

- [ ] **Step 4: Add router to `backend/app/main.py`**

In `create_app`, extend the import/include block to:
```python
    from app.api import routes_account, routes_trade, routes_market, routes_discovery
    app.include_router(routes_account.router)
    app.include_router(routes_trade.router)
    app.include_router(routes_market.router)
    app.include_router(routes_discovery.router)
```

- [ ] **Step 5: Run test, expect pass; then full suite**

Run: `.venv/bin/python -m pytest tests/test_api_discovery.py -v && .venv/bin/python -m pytest -q`
Expected: target PASS; whole suite PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/routes_discovery.py backend/app/main.py backend/tests/test_api_discovery.py
git commit -m "feat(api): GET /api/discovery (latest or by date)"
```

---

## Task 7: run_discovery.py script

**Files:**
- Create: `backend/scripts/run_discovery.py`

Thin orchestration; verified by a real run against the populated DB.

- [ ] **Step 1: Write `backend/scripts/run_discovery.py`**

```python
import argparse
import sys
from pathlib import Path
from datetime import date

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db.database import make_engine, make_session_factory, Base
import app.db.models  # noqa: F401
from app.data.quote_store import QuoteStore
from app.discovery.snapshot import QuoteStoreMarketHistory
from app.discovery.providers import MomentumProvider
from app.discovery.scorer import DiscoveryScorer
from app.discovery.runner import DiscoveryRunner


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--date", default=None, help="YYYY-MM-DD; default = latest in DB")
    p.add_argument("--window", type=int, default=20)
    args = p.parse_args()

    engine = make_engine(); Base.metadata.create_all(engine)
    session = make_session_factory(engine)()
    store = QuoteStore(session)

    as_of = (date(*map(int, args.date.split("-"))) if args.date
             else store.trading_dates(date.today(), 1)[0])
    runner = DiscoveryRunner(session, QuoteStoreMarketHistory(store),
                             [MomentumProvider()], DiscoveryScorer(top_n=8),
                             window=args.window)
    picks = runner.run(as_of)
    for code, score, raw in picks:
        print(f"{code}  score={score:.3f}  {raw}", flush=True)
    print(f"DISCOVERY_DONE as_of={as_of} picks={len(picks)}", flush=True)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Sanity check (parses + imports)**

Run (from `backend/`): `.venv/bin/python scripts/run_discovery.py --help`
Expected: argparse help prints, exit 0.

- [ ] **Step 3: Commit**

```bash
git add backend/scripts/run_discovery.py
git commit -m "feat(scripts): run_discovery daily 机会榜 Top-8 from the historical DB"
```

---

## Task 8: Frontend 机会榜 panel

**Files:**
- Create: `frontend/src/components/DiscoveryPanel.tsx`
- Modify: `frontend/src/pages/Dashboard.tsx`

- [ ] **Step 1: Write `frontend/src/components/DiscoveryPanel.tsx`**

```tsx
import { useEffect, useState } from "react";
import { apiGet } from "../api/client";

type Pick = { as_of: string; code: string; rank: number; score: number;
  factors: Record<string, number> };

export function DiscoveryPanel() {
  const [picks, setPicks] = useState<Pick[]>([]);
  useEffect(() => {
    apiGet<Pick[]>("/api/discovery").then(setPicks).catch(() => {});
  }, []);
  if (!picks.length) return <p>机会榜暂无数据</p>;
  return (
    <table>
      <thead><tr><th>#</th><th>代码</th><th>评分</th><th>因子</th></tr></thead>
      <tbody>
        {picks.map((p) => (
          <tr key={p.code}>
            <td>{p.rank}</td><td>{p.code}</td><td>{p.score.toFixed(3)}</td>
            <td>{Object.entries(p.factors).map(([k, v]) => `${k}:${v.toFixed(2)}`).join("  ")}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
```

- [ ] **Step 2: Add the panel to `frontend/src/pages/Dashboard.tsx`**

Add the import at the top:
```tsx
import { DiscoveryPanel } from "../components/DiscoveryPanel";
```
Then inside the dashboard's returned JSX, after the equity chart section, add:
```tsx
      <h2>机会榜 Top-8</h2>
      <DiscoveryPanel />
```

- [ ] **Step 3: Build to verify types**

Run: `cd frontend && npm run build`
Expected: build succeeds.

- [ ] **Step 4: Commit**

```bash
git add frontend/src -- ':!frontend/node_modules'
git commit -m "feat(frontend): 机会榜 Top-8 discovery panel on the dashboard"
```

---

## Task 9: Integration run + README

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Full backend suite**

Run (from `backend/`): `.venv/bin/python -m pytest -q`
Expected: all prior tests + new discovery tests PASS.

- [ ] **Step 2: Real discovery run against the populated DB**

```bash
cd backend && .venv/bin/python scripts/run_discovery.py
```
Expected: prints 8 `code score=... {...}` lines and `DISCOVERY_DONE as_of=... picks=8`.
Verify `GET /api/discovery` returns them; the dashboard 机会榜 panel shows the table.

- [ ] **Step 3: Add a "Discovery engine" section to `README.md`** (after the historical-quote-database section)

```markdown
## Discovery engine (机会榜)

Daily whole-market scan scoring price/volume momentum (mom_5d, turnover,
vol_ratio, breakout), percentile-normalized and equal-weighted, Top-8 persisted
to `discovery_picks`. Reads the historical quote DB via `QuoteStore` (no tushare
at scan time).

```bash
cd backend
.venv/bin/python scripts/run_discovery.py            # latest date in DB
.venv/bin/python scripts/run_discovery.py --date 2026-05-29
```

Surfaced at `GET /api/discovery` and the dashboard 机会榜 panel. Pluggable
`SignalProvider` — slice-4 qualitative/money-flow signals slot in as more providers.
```

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "docs: README section for the discovery engine (机会榜)"
```

---

## Self-Review (completed by author)

**Spec coverage:**
- Pluggable SignalProvider + MomentumProvider (4 factors) → Task 2 ✓
- DiscoveryScorer (percentile, weighted sum, Top-8, ties, full-coverage) → Task 3 ✓
- MarketHistory reading the DB (spec's qlib/MarketHistory adaptation) → Task 4 ✓
- discovery_picks model + idempotent persist → Tasks 1, 5 ✓
- GET /api/discovery latest + by-date → Task 6 ✓
- run_discovery runner → Tasks 5, 7 ✓
- Dashboard 机会榜 panel → Task 8 ✓
- Daily cadence, Top-N=8, interfaces+TDD → throughout ✓

**Placeholder scan:** none — every code step is complete; Tasks 7/9 are integration
with explicit run/verify commands.

**Type consistency:** `StockData(code, closes, highs, turnover, vol_ratio)` consistent
across snapshot/providers/history/tests. `SignalProvider.compute -> {factor: {code: val}}`
consumed unchanged by `DiscoveryScorer.score` and merged in `DiscoveryRunner`. Scorer
returns `(code, score, raw)` tuples consumed by runner + script. `DiscoveryPick` columns
(as_of, code, rank, score, factors) consistent across model, runner, API, frontend.

**Known risks (flagged):**
- Whole-market `get_range` over a 20-day window is ~115k rows — fine for SQLite at
  this scale; grouped in Python. A Postgres swap needs only `DATABASE_URL`.
- mom_5d/breakout need ≥6 / ≥1 trailing bars; early-listed stocks with short history
  are dropped from those factors (and thus from full-coverage scoring) — intended.
```
