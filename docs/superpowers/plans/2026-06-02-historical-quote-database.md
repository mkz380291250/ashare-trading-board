# Historical Quote Database Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a queryable whole-market A-share daily history (~5 years of raw OHLCV + adj_factor + daily_basic metrics) in SQL, populated by a resumable, idempotent, rate-limited (≤100 tushare calls/min) backfill, with a read interface returning `DailyBar`s.

**Architecture:** Two SQLAlchemy tables (`daily_quotes` wide table, `ingested_days` progress gate) on the existing slice-0+1 DB. A `RateLimiter` throttles tushare calls; a `MarketFetcher` pulls+merges `daily`/`daily_basic`/`adj_factor` for one trade date; a `QuoteStore` does idempotent upserts and reads. Backfill/daily-update scripts orchestrate over tested units, run detached.

**Tech Stack:** Python 3.11, SQLAlchemy 2.x, pandas, tushare, pytest. Reuses slice-1 `DailyBar` and `app/data/adjust.py`.

---

## Reference: Spec

`docs/superpowers/specs/2026-06-02-historical-quote-database-design.md`. Key constraints:
- Store **raw OHLCV + adj_factor + daily_basic metrics**; derive qfq/hfq on read.
- Whole-market, fetch by trade date; ~5 years.
- **≤ 100 tushare calls/min** (hard).
- Resumable + idempotent (per trade date); survives interruption.
- All tushare access behind interfaces, mocked in unit tests.

## File Structure

```
backend/
  app/
    db/models.py          # MODIFY: add DailyQuote, IngestedDay
    data/
      rate_limiter.py     # NEW: RateLimiter (≤N calls / period)
      market_fetch.py     # NEW: MarketFetcher.fetch_day(trade_date) -> rows
      quote_store.py      # NEW: QuoteStore (upsert/idempotent/resume/read)
  scripts/
    backfill_quotes.py    # NEW: resumable rate-limited backfill
    daily_update_quotes.py# NEW: incremental latest-day update
  tests/
    test_quote_models.py
    test_rate_limiter.py
    test_market_fetch.py
    test_quote_store.py
```

---

## Task 1: DailyQuote + IngestedDay models

**Files:**
- Modify: `backend/app/db/models.py`
- Test: `backend/tests/test_quote_models.py`

- [ ] **Step 1: Write failing test `backend/tests/test_quote_models.py`**

```python
from datetime import date
from app.db.models import DailyQuote, IngestedDay


def test_daily_quote_roundtrip(session):
    q = DailyQuote(code="600519.SH", trade_date=date(2026, 5, 29),
                   open=1270.0, high=1329.0, low=1270.0, close=1326.0,
                   pre_close=1275.98, vol=76478.0, amount=1.0e7, adj_factor=8.4464,
                   turnover_rate=0.6, volume_ratio=1.2, circ_mv=1.0e9,
                   total_mv=1.6e9, pe=30.0, pb=9.0)
    session.add(q); session.commit()
    got = session.get(DailyQuote, ("600519.SH", date(2026, 5, 29)))
    assert got.close == 1326.0 and got.adj_factor == 8.4464
    assert got.turnover_rate == 0.6


def test_ingested_day_pk(session):
    session.add(IngestedDay(trade_date=date(2026, 5, 29))); session.commit()
    assert session.get(IngestedDay, date(2026, 5, 29)) is not None
```

- [ ] **Step 2: Run test, expect failure**

Run (from `backend/`): `.venv/bin/python -m pytest tests/test_quote_models.py -v`
Expected: FAIL — `ImportError: cannot import name 'DailyQuote'`.

- [ ] **Step 3: Append models to `backend/app/db/models.py`**

```python
from sqlalchemy import Index

class DailyQuote(Base):
    __tablename__ = "daily_quotes"
    code: Mapped[str] = mapped_column(String(16), primary_key=True)
    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)
    open: Mapped[float] = mapped_column(Float)
    high: Mapped[float] = mapped_column(Float)
    low: Mapped[float] = mapped_column(Float)
    close: Mapped[float] = mapped_column(Float)
    pre_close: Mapped[float | None] = mapped_column(Float, nullable=True)
    vol: Mapped[float] = mapped_column(Float)
    amount: Mapped[float | None] = mapped_column(Float, nullable=True)
    adj_factor: Mapped[float] = mapped_column(Float, default=1.0)
    turnover_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    volume_ratio: Mapped[float | None] = mapped_column(Float, nullable=True)
    circ_mv: Mapped[float | None] = mapped_column(Float, nullable=True)
    total_mv: Mapped[float | None] = mapped_column(Float, nullable=True)
    pe: Mapped[float | None] = mapped_column(Float, nullable=True)
    pb: Mapped[float | None] = mapped_column(Float, nullable=True)

Index("ix_daily_quotes_trade_date", DailyQuote.trade_date)

class IngestedDay(Base):
    __tablename__ = "ingested_days"
    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)
```

(Keep the existing imports; `Index` is the only new symbol from sqlalchemy.)

- [ ] **Step 4: Run test, expect pass**

Run: `.venv/bin/python -m pytest tests/test_quote_models.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/app/db/models.py backend/tests/test_quote_models.py
git commit -m "feat(db): DailyQuote + IngestedDay models for historical quotes"
```

---

## Task 2: RateLimiter (≤ N calls per period)

**Files:**
- Create: `backend/app/data/rate_limiter.py`
- Test: `backend/tests/test_rate_limiter.py`

Sliding-window limiter with injectable clock + sleep so it is deterministic in tests. `acquire()` blocks (via injected sleep) until a call is permitted.

- [ ] **Step 1: Write failing test `backend/tests/test_rate_limiter.py`**

```python
from app.data.rate_limiter import RateLimiter


class FakeClock:
    def __init__(self): self.t = 0.0
    def now(self): return self.t
    def sleep(self, dt): self.t += dt  # sleeping advances time


def test_never_exceeds_max_in_window():
    clk = FakeClock()
    rl = RateLimiter(max_calls=100, period_s=60, now=clk.now, sleep=clk.sleep)
    times = []
    for _ in range(250):
        rl.acquire()
        times.append(clk.now())
    # for every call, count of calls within the preceding 60s window <= 100
    for i, t in enumerate(times):
        window = [u for u in times[: i + 1] if u > t - 60]
        assert len(window) <= 100


def test_first_100_are_immediate():
    clk = FakeClock()
    rl = RateLimiter(max_calls=100, period_s=60, now=clk.now, sleep=clk.sleep)
    for _ in range(100):
        rl.acquire()
    assert clk.now() == 0.0          # no sleep needed for first 100
    rl.acquire()                      # 101st must wait
    assert clk.now() > 0.0
```

- [ ] **Step 2: Run test, expect failure**

Run: `.venv/bin/python -m pytest tests/test_rate_limiter.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Write `backend/app/data/rate_limiter.py`**

```python
import time
from collections import deque


class RateLimiter:
    """Allow at most `max_calls` within any rolling `period_s` window."""

    def __init__(self, max_calls: int, period_s: float = 60.0,
                 now=time.monotonic, sleep=time.sleep):
        self.max_calls = max_calls
        self.period_s = period_s
        self._now = now
        self._sleep = sleep
        self._calls: deque[float] = deque()

    def acquire(self) -> None:
        t = self._now()
        # drop timestamps outside the window
        while self._calls and self._calls[0] <= t - self.period_s:
            self._calls.popleft()
        if len(self._calls) >= self.max_calls:
            wait = self._calls[0] + self.period_s - t
            if wait > 0:
                self._sleep(wait)
            t = self._now()
            while self._calls and self._calls[0] <= t - self.period_s:
                self._calls.popleft()
        self._calls.append(self._now())
```

- [ ] **Step 4: Run test, expect pass**

Run: `.venv/bin/python -m pytest tests/test_rate_limiter.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/app/data/rate_limiter.py backend/tests/test_rate_limiter.py
git commit -m "feat(data): sliding-window RateLimiter for tushare throttling"
```

---

## Task 3: MarketFetcher (whole-market day fetch + merge)

**Files:**
- Create: `backend/app/data/market_fetch.py`
- Test: `backend/tests/test_market_fetch.py`

Pulls `daily`, `daily_basic`, `adj_factor` for one trade date (each call gated by the limiter), merges on `ts_code`, returns row dicts shaped for `DailyQuote`.

- [ ] **Step 1: Write failing test `backend/tests/test_market_fetch.py`**

```python
from datetime import date
import pandas as pd
from app.data.market_fetch import MarketFetcher


class FakePro:
    def daily(self, trade_date):
        return pd.DataFrame({
            "ts_code": ["600519.SH", "000001.SZ"],
            "open": [1270.0, 11.0], "high": [1329.0, 11.5],
            "low": [1270.0, 10.8], "close": [1326.0, 11.0],
            "pre_close": [1275.98, 10.9], "vol": [76478.0, 2000.0],
            "amount": [1.0e7, 2.2e4],
        })

    def daily_basic(self, trade_date):
        return pd.DataFrame({
            "ts_code": ["600519.SH", "000001.SZ"],
            "turnover_rate": [0.6, 1.1], "volume_ratio": [1.2, 0.9],
            "circ_mv": [1.0e9, 2.0e8], "total_mv": [1.6e9, 3.0e8],
            "pe": [30.0, 5.0], "pb": [9.0, 0.6],
        })

    def adj_factor(self, trade_date):
        return pd.DataFrame({
            "ts_code": ["600519.SH", "000001.SZ"],
            "adj_factor": [8.4464, 12.3],
        })


class CountingLimiter:
    def __init__(self): self.n = 0
    def acquire(self): self.n += 1


def test_fetch_day_merges_three_sources():
    lim = CountingLimiter()
    f = MarketFetcher(pro=FakePro(), limiter=lim)
    rows = f.fetch_day(date(2026, 5, 29))
    assert lim.n == 3                     # one acquire per tushare call
    by = {r["code"]: r for r in rows}
    assert len(rows) == 2
    mt = by["600519.SH"]
    assert mt["trade_date"] == date(2026, 5, 29)
    assert mt["close"] == 1326.0 and mt["adj_factor"] == 8.4464
    assert mt["turnover_rate"] == 0.6 and mt["pb"] == 9.0


def test_missing_adj_factor_defaults_to_one():
    class NoAdjPro(FakePro):
        def adj_factor(self, trade_date):
            return pd.DataFrame({"ts_code": ["600519.SH"], "adj_factor": [8.4464]})
    f = MarketFetcher(pro=NoAdjPro(), limiter=CountingLimiter())
    by = {r["code"]: r for r in f.fetch_day(date(2026, 5, 29))}
    assert by["000001.SZ"]["adj_factor"] == 1.0   # no factor row -> default 1.0
```

- [ ] **Step 2: Run test, expect failure**

Run: `.venv/bin/python -m pytest tests/test_market_fetch.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Write `backend/app/data/market_fetch.py`**

```python
from datetime import date
import pandas as pd


def _fmt(d: date) -> str:
    return d.strftime("%Y%m%d")


class MarketFetcher:
    """Fetch + merge one trade date's whole-market quotes. tushare calls are
    routed through `limiter.acquire()` (a RateLimiter or compatible)."""

    def __init__(self, pro, limiter):
        self.pro = pro
        self.limiter = limiter

    def fetch_day(self, trade_date: date) -> list[dict]:
        ds = _fmt(trade_date)
        self.limiter.acquire(); daily = self.pro.daily(trade_date=ds)
        self.limiter.acquire(); basic = self.pro.daily_basic(trade_date=ds)
        self.limiter.acquire(); adj = self.pro.adj_factor(trade_date=ds)

        m = daily.merge(basic, on="ts_code", how="left")
        m = m.merge(adj[["ts_code", "adj_factor"]], on="ts_code", how="left")
        rows: list[dict] = []
        for _, r in m.iterrows():
            rows.append({
                "code": r["ts_code"], "trade_date": trade_date,
                "open": _f(r, "open"), "high": _f(r, "high"),
                "low": _f(r, "low"), "close": _f(r, "close"),
                "pre_close": _f(r, "pre_close"), "vol": _f(r, "vol"),
                "amount": _f(r, "amount"),
                "adj_factor": _f(r, "adj_factor", 1.0),
                "turnover_rate": _f(r, "turnover_rate"),
                "volume_ratio": _f(r, "volume_ratio"),
                "circ_mv": _f(r, "circ_mv"), "total_mv": _f(r, "total_mv"),
                "pe": _f(r, "pe"), "pb": _f(r, "pb"),
            })
        return rows


def _f(row, key: str, default=None):
    if key not in row or pd.isna(row[key]):
        return default
    return float(row[key])
```

- [ ] **Step 4: Run test, expect pass**

Run: `.venv/bin/python -m pytest tests/test_market_fetch.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/app/data/market_fetch.py backend/tests/test_market_fetch.py
git commit -m "feat(data): MarketFetcher merges daily+daily_basic+adj_factor per trade date"
```

---

## Task 4: QuoteStore (idempotent upsert, resume gate, reads)

**Files:**
- Create: `backend/app/data/quote_store.py`
- Test: `backend/tests/test_quote_store.py`

`upsert_day` is idempotent via `session.merge` (PK = code+trade_date). `ingested_dates`/`mark_ingested` drive resume. `get_bars` returns slice-1 `DailyBar`s; `get_market_on` returns rows for a date.

- [ ] **Step 1: Write failing test `backend/tests/test_quote_store.py`**

```python
from datetime import date
from app.data.quote_store import QuoteStore
from app.data.source import DailyBar


def _rows(d, close, factor):
    return [{"code": "X", "trade_date": d, "open": close, "high": close,
             "low": close, "close": close, "pre_close": close, "vol": 1000.0,
             "amount": 1.0, "adj_factor": factor, "turnover_rate": 0.5,
             "volume_ratio": 1.0, "circ_mv": 1.0, "total_mv": 1.0,
             "pe": 1.0, "pb": 1.0}]


def test_upsert_is_idempotent(session):
    qs = QuoteStore(session)
    qs.upsert_day(date(2026, 1, 2), _rows(date(2026, 1, 2), 10.0, 1.0))
    qs.upsert_day(date(2026, 1, 2), _rows(date(2026, 1, 2), 11.0, 1.0))  # same PK
    bars = qs.get_bars("X", date(2026, 1, 1), date(2026, 1, 5))
    assert len(bars) == 1            # no duplicate row
    assert bars[0].close == 11.0     # last write wins


def test_mark_and_resume(session):
    qs = QuoteStore(session)
    assert qs.ingested_dates() == set()
    qs.mark_ingested(date(2026, 1, 2))
    qs.mark_ingested(date(2026, 1, 3))
    assert qs.ingested_dates() == {date(2026, 1, 2), date(2026, 1, 3)}


def test_get_bars_returns_sorted_dailybars(session):
    qs = QuoteStore(session)
    qs.upsert_day(date(2026, 1, 3), _rows(date(2026, 1, 3), 11.0, 2.0))
    qs.upsert_day(date(2026, 1, 2), _rows(date(2026, 1, 2), 10.0, 1.0))
    bars = qs.get_bars("X", date(2026, 1, 1), date(2026, 1, 5))
    assert [b.trade_date for b in bars] == [date(2026, 1, 2), date(2026, 1, 3)]
    assert isinstance(bars[0], DailyBar)
    assert bars[0].adj_factor == 1.0 and bars[1].close == 11.0


def test_get_market_on(session):
    qs = QuoteStore(session)
    qs.upsert_day(date(2026, 1, 2), _rows(date(2026, 1, 2), 10.0, 1.0))
    rows = qs.get_market_on(date(2026, 1, 2))
    assert len(rows) == 1 and rows[0].code == "X"
```

- [ ] **Step 2: Run test, expect failure**

Run: `.venv/bin/python -m pytest tests/test_quote_store.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Write `backend/app/data/quote_store.py`**

```python
from datetime import date
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.db.models import DailyQuote, IngestedDay
from app.data.source import DailyBar


class QuoteStore:
    def __init__(self, session: Session):
        self.s = session

    def upsert_day(self, trade_date: date, rows: list[dict]) -> None:
        for r in rows:
            self.s.merge(DailyQuote(**r))   # PK (code, trade_date) -> insert or update
        self.s.commit()

    def mark_ingested(self, trade_date: date) -> None:
        self.s.merge(IngestedDay(trade_date=trade_date))
        self.s.commit()

    def ingested_dates(self) -> set[date]:
        return set(self.s.scalars(select(IngestedDay.trade_date)).all())

    def get_market_on(self, trade_date: date) -> list[DailyQuote]:
        return list(self.s.scalars(
            select(DailyQuote).where(DailyQuote.trade_date == trade_date)
        ).all())

    def get_bars(self, code: str, start: date, end: date) -> list[DailyBar]:
        rows = self.s.scalars(
            select(DailyQuote).where(
                DailyQuote.code == code,
                DailyQuote.trade_date >= start,
                DailyQuote.trade_date <= end,
            ).order_by(DailyQuote.trade_date)
        ).all()
        return [DailyBar(code=r.code, trade_date=r.trade_date, open=r.open,
                         high=r.high, low=r.low, close=r.close, volume=r.vol,
                         adj_factor=r.adj_factor) for r in rows]
```

- [ ] **Step 4: Run test, expect pass**

Run: `.venv/bin/python -m pytest tests/test_quote_store.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/app/data/quote_store.py backend/tests/test_quote_store.py
git commit -m "feat(data): QuoteStore idempotent upsert, resume gate, DailyBar reads"
```

---

## Task 5: Backfill script (resumable, rate-limited)

**Files:**
- Create: `backend/scripts/backfill_quotes.py`

Thin orchestration over tested units. Verified by a real detached run (not a unit test).

- [ ] **Step 1: Write `backend/scripts/backfill_quotes.py`**

```python
import argparse
import sys
from pathlib import Path
from datetime import date

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # make `app` importable

from app.config import get_settings
from app.db.database import make_engine, make_session_factory, Base
import app.db.models  # noqa: F401
from app.data.rate_limiter import RateLimiter
from app.data.market_fetch import MarketFetcher
from app.data.quote_store import QuoteStore


def _d(x: str) -> date:
    return date(int(x[:4]), int(x[4:6]), int(x[6:8]))


def trading_days(pro, limiter, start: str, end: str) -> list[date]:
    limiter.acquire()
    cal = pro.trade_cal(start_date=start, end_date=end)
    open_days = cal[cal["is_open"] == 1]["cal_date"].tolist()
    return sorted(_d(str(x)) for x in open_days)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--start", default="20210101")
    p.add_argument("--end", default=date.today().strftime("%Y%m%d"))
    p.add_argument("--max-per-min", type=int, default=100)
    args = p.parse_args()

    s = get_settings()
    import tushare as ts
    ts.set_token(s.tushare_token)
    pro = ts.pro_api()

    engine = make_engine()
    Base.metadata.create_all(engine)
    session = make_session_factory(engine)()
    store = QuoteStore(session)
    limiter = RateLimiter(max_calls=args.max_per_min, period_s=60.0)
    fetcher = MarketFetcher(pro=pro, limiter=limiter)

    days = trading_days(pro, limiter, args.start, args.end)
    done = store.ingested_dates()
    todo = [d for d in days if d not in done]
    print(f"calendar={len(days)} done={len(done)} todo={len(todo)}", flush=True)

    for i, d in enumerate(todo, 1):
        try:
            rows = fetcher.fetch_day(d)
            store.upsert_day(d, rows)
            store.mark_ingested(d)
            print(f"[{i}/{len(todo)}] {d}: {len(rows)} rows", flush=True)
        except Exception as e:  # leave day un-ingested -> retried next run
            print(f"[{i}/{len(todo)}] {d}: ERROR {e!r} (will retry next run)", flush=True)
    print("BACKFILL_DONE", flush=True)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Sanity check (no network) — script imports + --help**

Run (from `backend/`): `.venv/bin/python scripts/backfill_quotes.py --help`
Expected: argparse help prints, exit 0 (proves imports resolve).

- [ ] **Step 3: Commit**

```bash
git add backend/scripts/backfill_quotes.py
git commit -m "feat(scripts): resumable rate-limited whole-market quote backfill"
```

- [ ] **Step 4: Real detached backfill (integration — run, do not block)**

Set `DATABASE_URL` (sqlite ok). Run **detached** (the job is long; ≤100/min → ~40 min for 5y):

```bash
cd backend
setsid bash -c '.venv/bin/python scripts/backfill_quotes.py --start 20210101 > /tmp/backfill.log 2>&1; echo EXIT=$? >> /tmp/backfill.log' </dev/null >/dev/null 2>&1 &
```

Then poll `/tmp/backfill.log` for progress; a background watcher should wait for `BACKFILL_DONE` or `EXIT=`. If interrupted, **just rerun the same command** — ingested days are skipped.

Expected: `daily_quotes` populated for whole market across the window; `ingested_days` count == trading-day count. Verify:

```bash
.venv/bin/python -c "
import sqlite3; c=sqlite3.connect('ashare.db')
print('quote rows', c.execute('select count(*) from daily_quotes').fetchone()[0])
print('ingested days', c.execute('select count(*) from ingested_days').fetchone()[0])
print('distinct codes', c.execute('select count(distinct code) from daily_quotes').fetchone()[0])
"
```

---

## Task 6: Daily incremental update script

**Files:**
- Create: `backend/scripts/daily_update_quotes.py`

- [ ] **Step 1: Write `backend/scripts/daily_update_quotes.py`**

```python
import argparse
import sys
from pathlib import Path
from datetime import date, timedelta

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # make `app` importable

from app.config import get_settings
from app.db.database import make_engine, make_session_factory, Base
import app.db.models  # noqa: F401
from app.data.rate_limiter import RateLimiter
from app.data.market_fetch import MarketFetcher
from app.data.quote_store import QuoteStore
from scripts.backfill_quotes import trading_days


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--days", type=int, default=7)  # look-back window
    p.add_argument("--max-per-min", type=int, default=100)
    args = p.parse_args()

    s = get_settings()
    import tushare as ts
    ts.set_token(s.tushare_token)
    pro = ts.pro_api()

    engine = make_engine()
    Base.metadata.create_all(engine)
    session = make_session_factory(engine)()
    store = QuoteStore(session)
    limiter = RateLimiter(max_calls=args.max_per_min, period_s=60.0)
    fetcher = MarketFetcher(pro=pro, limiter=limiter)

    end = date.today(); start = end - timedelta(days=args.days)
    days = trading_days(pro, limiter, start.strftime("%Y%m%d"), end.strftime("%Y%m%d"))
    done = store.ingested_dates()
    for d in [x for x in days if x not in done]:
        rows = fetcher.fetch_day(d)
        store.upsert_day(d, rows); store.mark_ingested(d)
        print(f"{d}: {len(rows)} rows", flush=True)
    print("UPDATE_DONE", flush=True)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Sanity check — imports + --help**

Run: `.venv/bin/python scripts/daily_update_quotes.py --help`
Expected: argparse help prints, exit 0.

- [ ] **Step 3: Commit**

```bash
git add backend/scripts/daily_update_quotes.py
git commit -m "feat(scripts): daily incremental quote update (reuses backfill core)"
```

---

## Task 7: Full-suite check + README note

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Run the full backend test suite**

Run (from `backend/`): `.venv/bin/python -m pytest -q`
Expected: all prior slice-0+1 tests PASS plus the new model/limiter/fetch/store tests (≈ 29 tests).

- [ ] **Step 2: Add a "Historical quote database" section to `README.md`**

Document: the two tables, the backfill command (with `--max-per-min 100`),
resumability ("rerun to resume"), the incremental command, and `QuoteStore`
as the read path for the discovery engine.

```markdown
## Historical quote database

Whole-market ~5y daily history in `daily_quotes` (+ `ingested_days` progress).

```bash
cd backend
# resumable, rate-limited (<=100 tushare calls/min); rerun to resume
.venv/bin/python scripts/backfill_quotes.py --start 20210101 --max-per-min 100
# daily incremental
.venv/bin/python scripts/daily_update_quotes.py --days 7
```

Read via `app/data/quote_store.py::QuoteStore` (returns `DailyBar`s; apply
`to_qfq`/`to_hfq` from `app/data/adjust.py`). The discovery engine reads from
this DB instead of fetching tushare at scan time.
```

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: README section for historical quote database"
```

---

## Self-Review (completed by author)

**Spec coverage:**
- SQL `daily_quotes` wide table (OHLCV+adj_factor+daily_basic) → Task 1 ✓
- `ingested_days` progress gate → Task 1, 4 ✓
- ≤100 calls/min → Task 2 (RateLimiter) + wired in Tasks 5/6 ✓
- whole-market fetch + merge of 3 endpoints → Task 3 ✓
- idempotent upsert + resume → Task 4 (merge + ingested gate), tested ✓
- read interface returns DailyBar / market rows → Task 4 ✓
- resumable detached backfill, ~40min → Task 5 ✓
- daily incremental → Task 6 ✓
- raw prices + adj_factor, qfq/hfq on read → Task 1/4 store raw; reuse adjust.py ✓

**Placeholder scan:** none — every code step is complete; Tasks 5/6 are
integration scripts with explicit run/verify commands.

**Type consistency:** `MarketFetcher.fetch_day` returns row dicts whose keys
match `DailyQuote` columns exactly and are consumed unchanged by
`QuoteStore.upsert_day(**r)`. `QuoteStore.get_bars` builds slice-1 `DailyBar`
(fields: code, trade_date, open, high, low, close, volume, adj_factor). Limiter
interface (`acquire()`) consistent across RateLimiter, MarketFetcher, tests, scripts.

**Known execution risks (flagged):**
- tushare points level may rate-limit below 100/min or gate `daily_basic`/`trade_cal`;
  the limiter + per-day retry + resume make this safe (slow, not broken).
- SQLite write throughput for whole-market upserts is fine at this scale; a
  Postgres swap only needs `DATABASE_URL` change (schema is PG-compatible).
```
