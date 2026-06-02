# Theme Screener & Watch Pool Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Daily-screen hot-theme A-share stocks (NVIDIA compute chain / 半导体芯片 / 算力 / 电力) that printed a >7% bullish candle in the last 3 days, have strong earnings (net-profit YoY ≥20% & revenue YoY >0), and are not extended (≤85% of 52w high & 60d return <50%), then track each pick's T+1/3/5/10 forward returns.

**Architecture:** New `backend/app/screener/` module reusing `app/data` (`QuoteStore`, historical quote DB). Pure-logic filters (big-yang, not-at-top, forward returns) are TDD-first. Theme membership and earnings are behind `ThemeSource`/`EarningsSource` interfaces (tushare impl + static fallback), mocked in tests. A `WatchPool` persists picks and updates forward returns. A daily runner, a REST endpoint, and a "选股池" frontend page surface results.

**Tech Stack:** Python 3.11, SQLAlchemy 2.x, pandas, tushare, pytest; React + Vite + TS frontend. Reuses slice-1 `DailyBar`, `app/data/quote_store.py`.

---

## Reference: Spec

`docs/superpowers/specs/2026-06-02-theme-screener-design.md`. Filters: theme ∧
big-yang(>7%, last 3d, close>open) ∧ earnings(np_yoy≥20% ∧ rev_yoy>0) ∧
not-top(close≤0.85×52w-high ∧ 60d-return<50%). Track T+1/3/5/10.

## File Structure

```
backend/
  app/
    screener/
      __init__.py
      filters.py        # NEW: pure logic — big_yang, not_at_top, forward_return, day_pct
      themes.py         # NEW: ThemeSource ABC + StaticThemeSource + TushareThemeSource
      earnings.py       # NEW: EarningsSource ABC + TushareEarningsSource ; Earnings dataclass
      pool.py           # NEW: WatchPool (add idempotent, update_forward_returns, list)
      screener.py       # NEW: Screener.run(as_of) -> list[Pick]
    db/models.py        # MODIFY: add WatchPoolEntry
    api/routes_screener.py  # NEW: GET /api/screener/picks
    main.py             # MODIFY: include screener router
  scripts/
    spike_screener.py   # NEW: verify tushare concept + fina_indicator (Task 0)
    run_screener.py     # NEW: daily orchestration
  tests/
    test_screener_filters.py
    test_screener_themes.py
    test_screener_earnings.py
    test_watch_pool.py
    test_screener_run.py
    test_api_screener.py
frontend/src/
  pages/ScreenerPool.tsx     # NEW
  components/PicksTable.tsx   # NEW
```

---

## Task 0: Spike — tushare concept + earnings endpoints

**Why first:** theme membership and earnings depend on tushare endpoints that may
be gated by the user's points. Verify before building. No unit tests — a gate.

**Files:**
- Create: `backend/scripts/spike_screener.py`

- [ ] **Step 1: Write `backend/scripts/spike_screener.py`**

```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings


def main():
    import tushare as ts
    pro = ts.pro_api(get_settings().tushare_token)
    # concept membership (Tonghuashun). If gated, note fallback to static lists.
    try:
        idx = pro.ths_index()  # concept/industry index list
        print("ths_index ok", idx.shape, list(idx.columns)[:6])
        sample = idx[idx["type"] == "N"].head(1)["ts_code"].tolist()
        if sample:
            mem = pro.ths_member(ts_code=sample[0])
            print("ths_member ok", sample[0], mem.shape)
    except Exception as e:
        print("CONCEPT GATED ->", repr(e), "(fallback: StaticThemeSource)")
    # earnings: net-profit YoY + revenue YoY
    try:
        fi = pro.fina_indicator(ts_code="600519.SH", period="20251231")
        cols = [c for c in fi.columns if "yoy" in c or "profit" in c]
        print("fina_indicator ok", fi.shape, cols[:8])
    except Exception as e:
        print("EARNINGS GATED ->", repr(e))


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run the spike**

Run (from `backend/`, `.env` populated): `.venv/bin/python scripts/spike_screener.py`
Expected: prints shapes for `ths_index`/`ths_member` and `fina_indicator`, OR a
"GATED" note. **Record results in `docs/superpowers/plans/spike-notes.md`** (append
a "Theme screener spike" section). If concept is gated, Task 3's `TushareThemeSource`
is skipped and `StaticThemeSource` (curated lists) is the default — not a blocker.

- [ ] **Step 3: Commit**

```bash
git add backend/scripts/spike_screener.py docs/superpowers/plans/spike-notes.md
git commit -m "chore(screener): spike tushare concept + earnings endpoints"
```

---

## Task 1: Pure-logic filters (big-yang, not-at-top, forward return)

**Files:**
- Create: `backend/app/screener/__init__.py`, `backend/app/screener/filters.py`
- Test: `backend/tests/test_screener_filters.py`

Inputs are slice-1 `DailyBar` lists (ascending by date) from `QuoteStore.get_bars`.

- [ ] **Step 1: Write failing test `backend/tests/test_screener_filters.py`**

```python
from datetime import date
from app.data.source import DailyBar
from app.screener.filters import has_big_yang, not_at_top, forward_return


def _bar(d, o, c, h=None, l=None):
    return DailyBar("X", d, o, h or max(o, c), l or min(o, c), c, 1000, 1.0)


def test_big_yang_detects_gt7pct_green_in_window():
    bars = [_bar(date(2026, 1, 1), 10, 10.0), _bar(date(2026, 1, 2), 10, 10.1),
            _bar(date(2026, 1, 5), 10.1, 10.9)]  # 10.1 -> 10.9 = +7.92%, green
    assert has_big_yang(bars, window=3, threshold=7.0) is True


def test_big_yang_exactly_7pct_fails():
    bars = [_bar(date(2026, 1, 1), 10, 10.0), _bar(date(2026, 1, 2), 10, 10.7)]  # +7.0%
    assert has_big_yang(bars, window=3, threshold=7.0) is False  # strictly >7


def test_big_yang_red_candle_excluded():
    # +8% on close vs prev close but close<open (gap up then fade) -> not green
    bars = [_bar(date(2026, 1, 1), 10, 10.0), _bar(date(2026, 1, 2), 11.0, 10.8)]
    assert has_big_yang(bars, window=3, threshold=7.0) is False


def test_big_yang_outside_window_excluded():
    bars = [_bar(date(2026, 1, 1), 10, 11.0),  # +10% but 3 days before the last
            _bar(date(2026, 1, 2), 11, 11.0), _bar(date(2026, 1, 5), 11, 11.0),
            _bar(date(2026, 1, 6), 11, 11.0)]
    assert has_big_yang(bars, window=3, threshold=7.0) is False


def test_not_at_top_true_when_below_high_and_calm():
    # last close 85 vs 52w high 100 -> exactly 0.85 boundary passes (<=); 60d ret small
    bars = [_bar(date(2026, 1, i + 1), 100, 100.0, h=100) for i in range(60)]
    bars += [_bar(date(2026, 3, 1), 85, 85.0, h=85)]
    assert not_at_top(bars, high_frac=0.85, max_ret=0.5) is True


def test_not_at_top_false_when_near_high():
    bars = [_bar(date(2026, 1, i + 1), 100, 100.0, h=100) for i in range(60)]
    bars += [_bar(date(2026, 3, 1), 95, 95.0, h=95)]  # 95 > 0.85*100
    assert not_at_top(bars, high_frac=0.85, max_ret=0.5) is False


def test_not_at_top_false_when_60d_return_too_high():
    bars = [_bar(date(2026, 1, 1), 10, 10.0, h=10)]
    bars += [_bar(date(2026, 1, i + 2), 16, 16.0, h=100) for i in range(60)]  # 10->16 = +60%
    assert not_at_top(bars, high_frac=0.85, max_ret=0.5) is False


def test_forward_return():
    assert forward_return(10.0, 12.0) == 0.2
    assert forward_return(10.0, None) is None
```

- [ ] **Step 2: Run test, expect failure**

Run: `.venv/bin/python -m pytest tests/test_screener_filters.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Write `backend/app/screener/filters.py`**

```python
from app.data.source import DailyBar


def day_pct(prev_close: float, close: float) -> float:
    return (close - prev_close) / prev_close * 100.0


def has_big_yang(bars: list[DailyBar], window: int = 3, threshold: float = 7.0) -> bool:
    """True if any of the last `window` bars rose > threshold% vs the prior close
    and closed above its open (a real bullish candle)."""
    if len(bars) < 2:
        return False
    n = len(bars)
    for i in range(max(1, n - window), n):
        b, prev = bars[i], bars[i - 1]
        if day_pct(prev.close, b.close) > threshold and b.close > b.open:
            return True
    return False


def not_at_top(bars: list[DailyBar], high_lookback: int = 252, ret_lookback: int = 60,
               high_frac: float = 0.85, max_ret: float = 0.5) -> bool:
    """True if last close <= high_frac * (max high over high_lookback) AND the
    cumulative return over the last ret_lookback bars < max_ret."""
    if not bars:
        return False
    last = bars[-1].close
    high = max(b.high for b in bars[-high_lookback:])
    if last > high_frac * high:
        return False
    ref = bars[-ret_lookback].close if len(bars) > ret_lookback else bars[0].close
    cum_ret = (last - ref) / ref
    return cum_ret < max_ret


def forward_return(entry_close: float, future_close: float | None) -> float | None:
    if future_close is None:
        return None
    return future_close / entry_close - 1.0
```

Create empty `backend/app/screener/__init__.py`.

- [ ] **Step 4: Run test, expect pass**

Run: `.venv/bin/python -m pytest tests/test_screener_filters.py -v`
Expected: PASS (8 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/app/screener/__init__.py backend/app/screener/filters.py backend/tests/test_screener_filters.py
git commit -m "feat(screener): pure-logic filters (big-yang, not-at-top, forward return)"
```

---

## Task 2: ThemeSource (membership) — interface + static + tushare

**Files:**
- Create: `backend/app/screener/themes.py`
- Test: `backend/tests/test_screener_themes.py`

- [ ] **Step 1: Write failing test `backend/tests/test_screener_themes.py`**

```python
from app.screener.themes import StaticThemeSource, TushareThemeSource


def test_static_theme_source():
    src = StaticThemeSource({"算力": ["A.SH", "B.SZ"], "电力": ["C.SH"]})
    assert src.themes() == ["算力", "电力"]
    assert src.members("算力") == ["A.SH", "B.SZ"]
    assert src.members("missing") == []


class FakePro:
    def ths_member(self, ts_code):
        import pandas as pd
        return pd.DataFrame({"con_code": ["A.SH", "B.SZ"]})


def test_tushare_theme_source_maps_index_to_members():
    src = TushareThemeSource(pro=FakePro(), index_by_theme={"算力": "885001.TI"})
    assert src.themes() == ["算力"]
    assert src.members("算力") == ["A.SH", "B.SZ"]
```

- [ ] **Step 2: Run test, expect failure**

Run: `.venv/bin/python -m pytest tests/test_screener_themes.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Write `backend/app/screener/themes.py`**

```python
from abc import ABC, abstractmethod


class ThemeSource(ABC):
    @abstractmethod
    def themes(self) -> list[str]: ...
    @abstractmethod
    def members(self, theme: str) -> list[str]: ...


class StaticThemeSource(ThemeSource):
    """Curated theme -> codes (fallback when tushare concept API is gated)."""

    def __init__(self, mapping: dict[str, list[str]]):
        self._m = mapping

    def themes(self) -> list[str]:
        return list(self._m.keys())

    def members(self, theme: str) -> list[str]:
        return list(self._m.get(theme, []))


class TushareThemeSource(ThemeSource):
    """theme -> concept index code -> member stock codes via ths_member."""

    def __init__(self, pro, index_by_theme: dict[str, str]):
        self.pro = pro
        self._idx = index_by_theme

    def themes(self) -> list[str]:
        return list(self._idx.keys())

    def members(self, theme: str) -> list[str]:
        code = self._idx.get(theme)
        if not code:
            return []
        df = self.pro.ths_member(ts_code=code)
        return [str(x) for x in df["con_code"].tolist()]
```

- [ ] **Step 4: Run test, expect pass**

Run: `.venv/bin/python -m pytest tests/test_screener_themes.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/app/screener/themes.py backend/tests/test_screener_themes.py
git commit -m "feat(screener): ThemeSource interface with static + tushare impls"
```

---

## Task 3: EarningsSource (net-profit & revenue YoY)

**Files:**
- Create: `backend/app/screener/earnings.py`
- Test: `backend/tests/test_screener_earnings.py`

- [ ] **Step 1: Write failing test `backend/tests/test_screener_earnings.py`**

```python
from app.screener.earnings import Earnings, TushareEarningsSource, passes_earnings


def test_passes_earnings_rule():
    assert passes_earnings(Earnings(np_yoy=25.0, rev_yoy=5.0)) is True
    assert passes_earnings(Earnings(np_yoy=20.0, rev_yoy=5.0)) is True   # >=20
    assert passes_earnings(Earnings(np_yoy=19.9, rev_yoy=5.0)) is False
    assert passes_earnings(Earnings(np_yoy=30.0, rev_yoy=0.0)) is False  # rev must be >0
    assert passes_earnings(None) is False


class FakePro:
    def fina_indicator(self, ts_code, **kw):
        import pandas as pd
        return pd.DataFrame({"end_date": ["20251231"], "netprofit_yoy": [25.0],
                             "or_yoy": [5.0]})


def test_tushare_earnings_latest():
    src = TushareEarningsSource(pro=FakePro())
    e = src.latest("600519.SH")
    assert e.np_yoy == 25.0 and e.rev_yoy == 5.0
```

- [ ] **Step 2: Run test, expect failure**

Run: `.venv/bin/python -m pytest tests/test_screener_earnings.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Write `backend/app/screener/earnings.py`**

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class Earnings:
    np_yoy: float    # net profit YoY %
    rev_yoy: float   # revenue YoY %


def passes_earnings(e: "Earnings | None", min_np_yoy: float = 20.0) -> bool:
    if e is None:
        return False
    return e.np_yoy >= min_np_yoy and e.rev_yoy > 0.0


class EarningsSource(ABC):
    @abstractmethod
    def latest(self, code: str) -> "Earnings | None": ...


class TushareEarningsSource(EarningsSource):
    def __init__(self, pro):
        self.pro = pro

    def latest(self, code: str) -> "Earnings | None":
        df = self.pro.fina_indicator(ts_code=code)
        if df is None or df.empty:
            return None
        df = df.sort_values("end_date")
        r = df.iloc[-1]
        import pandas as pd
        np_yoy = float(r["netprofit_yoy"]) if pd.notna(r.get("netprofit_yoy")) else 0.0
        rev_yoy = float(r["or_yoy"]) if pd.notna(r.get("or_yoy")) else 0.0
        return Earnings(np_yoy=np_yoy, rev_yoy=rev_yoy)
```

- [ ] **Step 4: Run test, expect pass**

Run: `.venv/bin/python -m pytest tests/test_screener_earnings.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/app/screener/earnings.py backend/tests/test_screener_earnings.py
git commit -m "feat(screener): EarningsSource + earnings rule (np_yoy>=20 & rev_yoy>0)"
```

---

## Task 4: WatchPoolEntry model + WatchPool persistence

**Files:**
- Modify: `backend/app/db/models.py`
- Create: `backend/app/screener/pool.py`
- Test: `backend/tests/test_watch_pool.py`

- [ ] **Step 1: Write failing test `backend/tests/test_watch_pool.py`**

```python
from datetime import date
from app.data.source import DailyBar
from app.screener.pool import WatchPool


def _bars(start_close):
    # 12 ascending trading days from 2026-01-02, close grows by 1 each day
    out = []
    for i in range(12):
        d = date(2026, 1, 2 + i)
        c = start_close + i
        out.append(DailyBar("X", d, c, c, c, c, 1000, 1.0))
    return out


def test_add_is_idempotent(session):
    wp = WatchPool(session)
    wp.add(code="X", theme="算力", on=date(2026, 1, 2), entry_close=10.0, trigger={"a": 1})
    wp.add(code="X", theme="算力", on=date(2026, 1, 2), entry_close=11.0, trigger={"a": 2})
    picks = wp.list()
    assert len(picks) == 1
    assert picks[0].entry_close == 10.0   # first selection preserved


def test_update_forward_returns(session):
    wp = WatchPool(session)
    wp.add(code="X", theme="算力", on=date(2026, 1, 2), entry_close=10.0, trigger={})
    # bars: entry day close=10 (index0); +1 each day -> T+1=11,T+3=13,T+5=15,T+10=20
    wp.update_forward_returns("X", date(2026, 1, 2), _bars(10.0))
    p = wp.list()[0]
    assert abs(p.ret_t1 - 0.1) < 1e-9    # 11/10 - 1
    assert abs(p.ret_t3 - 0.3) < 1e-9
    assert abs(p.ret_t5 - 0.5) < 1e-9
    assert abs(p.ret_t10 - 1.0) < 1e-9
```

- [ ] **Step 2: Run test, expect failure**

Run: `.venv/bin/python -m pytest tests/test_watch_pool.py -v`
Expected: FAIL — `app.screener.pool` / `WatchPoolEntry` missing.

- [ ] **Step 3: Append `WatchPoolEntry` to `backend/app/db/models.py`**

```python
class WatchPoolEntry(Base):
    __tablename__ = "watch_pool"
    code: Mapped[str] = mapped_column(String(16), primary_key=True)
    first_selected_on: Mapped[date] = mapped_column(Date, primary_key=True)
    theme: Mapped[str] = mapped_column(String(32))
    entry_close: Mapped[float] = mapped_column(Float)
    trigger: Mapped[str] = mapped_column(String, default="{}")  # JSON text
    ret_t1: Mapped[float | None] = mapped_column(Float, nullable=True)
    ret_t3: Mapped[float | None] = mapped_column(Float, nullable=True)
    ret_t5: Mapped[float | None] = mapped_column(Float, nullable=True)
    ret_t10: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_updated: Mapped[date | None] = mapped_column(Date, nullable=True)
```

- [ ] **Step 4: Write `backend/app/screener/pool.py`**

```python
import json
from datetime import date
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.db.models import WatchPoolEntry
from app.data.source import DailyBar
from app.screener.filters import forward_return

_OFFSETS = {"ret_t1": 1, "ret_t3": 3, "ret_t5": 5, "ret_t10": 10}


class WatchPool:
    def __init__(self, session: Session):
        self.s = session

    def get(self, code: str, on: date) -> WatchPoolEntry | None:
        return self.s.get(WatchPoolEntry, (code, on))

    def add(self, code: str, theme: str, on: date, entry_close: float, trigger: dict) -> None:
        if self.get(code, on) is not None:
            return                      # idempotent: keep the first selection
        self.s.add(WatchPoolEntry(code=code, first_selected_on=on, theme=theme,
                                  entry_close=entry_close, trigger=json.dumps(trigger)))
        self.s.commit()

    def update_forward_returns(self, code: str, on: date, bars: list[DailyBar]) -> None:
        entry = self.get(code, on)
        if entry is None:
            return
        closes = [b.close for b in bars if b.trade_date >= on]  # index 0 == entry day
        for field, n in _OFFSETS.items():
            fut = closes[n] if len(closes) > n else None
            setattr(entry, field, forward_return(entry.entry_close, fut))
        entry.last_updated = bars[-1].trade_date if bars else on
        self.s.commit()

    def list(self) -> list[WatchPoolEntry]:
        return list(self.s.scalars(
            select(WatchPoolEntry).order_by(WatchPoolEntry.first_selected_on.desc())
        ).all())
```

- [ ] **Step 5: Run test, expect pass**

Run: `.venv/bin/python -m pytest tests/test_watch_pool.py -v`
Expected: PASS (2 tests).

- [ ] **Step 6: Commit**

```bash
git add backend/app/db/models.py backend/app/screener/pool.py backend/tests/test_watch_pool.py
git commit -m "feat(screener): WatchPoolEntry model + WatchPool idempotent add & forward returns"
```

---

## Task 5: Screener orchestrator

**Files:**
- Create: `backend/app/screener/screener.py`
- Test: `backend/tests/test_screener_run.py`

Combines ThemeSource members + QuoteStore bars + EarningsSource into qualifying
picks. Uses a `bars_provider(code) -> list[DailyBar]` callable so tests inject
fakes without a DB.

- [ ] **Step 1: Write failing test `backend/tests/test_screener_run.py`**

```python
from datetime import date
from app.data.source import DailyBar
from app.screener.themes import StaticThemeSource
from app.screener.earnings import Earnings, EarningsSource
from app.screener.screener import Screener


def _bar(d, o, c, h=None):
    return DailyBar("PASS.SH", d, o, h or max(o, c), min(o, c), c, 1000, 1.0)


def _good_bars():
    # 60 calm days at 10, then a >7% green candle to 10.9; last close 10.9 well below
    # 52w-high (use high=12 cap) and 60d return small
    bars = [DailyBar("PASS.SH", date(2026, 1, 1), 10, 11, 9, 10.0, 1000, 1.0)]
    for i in range(60):
        bars.append(DailyBar("PASS.SH", date(2026, 2, 1) if False else date(2026, 1, 1),
                             10, 10, 10, 10.0, 1000, 1.0))
    # rebuild cleanly with ascending unique dates
    bars = []
    from datetime import timedelta
    d0 = date(2026, 1, 1)
    for i in range(60):
        bars.append(DailyBar("PASS.SH", d0 + timedelta(days=i), 10, 10.2, 9.8, 10.0, 1000, 1.0))
    bars.append(DailyBar("PASS.SH", d0 + timedelta(days=60), 10.1, 10.95, 10.0, 10.9, 1000, 1.0))
    return bars


class FakeEarnings(EarningsSource):
    def latest(self, code):
        return Earnings(np_yoy=25.0, rev_yoy=5.0)


def test_screener_selects_qualifying_stock():
    themes = StaticThemeSource({"算力": ["PASS.SH"]})
    bars = {"PASS.SH": _good_bars()}
    sc = Screener(themes=themes, earnings=FakeEarnings(),
                  bars_provider=lambda code: bars[code])
    picks = sc.run(as_of=_good_bars()[-1].trade_date)
    assert len(picks) == 1
    p = picks[0]
    assert p.code == "PASS.SH" and p.theme == "算力"
    assert p.entry_close == 10.9


def test_screener_rejects_weak_earnings():
    class Weak(EarningsSource):
        def latest(self, code): return Earnings(np_yoy=5.0, rev_yoy=1.0)
    themes = StaticThemeSource({"算力": ["PASS.SH"]})
    bars = {"PASS.SH": _good_bars()}
    sc = Screener(themes=themes, earnings=Weak(), bars_provider=lambda c: bars[c])
    assert sc.run(as_of=_good_bars()[-1].trade_date) == []
```

- [ ] **Step 2: Run test, expect failure**

Run: `.venv/bin/python -m pytest tests/test_screener_run.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Write `backend/app/screener/screener.py`**

```python
from dataclasses import dataclass
from datetime import date
from app.data.source import DailyBar
from app.screener.themes import ThemeSource
from app.screener.earnings import EarningsSource, passes_earnings
from app.screener.filters import has_big_yang, not_at_top, day_pct


@dataclass(frozen=True)
class Pick:
    code: str
    theme: str
    as_of: date
    entry_close: float
    trigger: dict


class Screener:
    def __init__(self, themes: ThemeSource, earnings: EarningsSource, bars_provider):
        self.themes = themes
        self.earnings = earnings
        self.bars_provider = bars_provider  # code -> list[DailyBar] (ascending)

    def run(self, as_of: date) -> list[Pick]:
        picks: list[Pick] = []
        seen: set[str] = set()
        for theme in self.themes.themes():
            for code in self.themes.members(theme):
                if code in seen:
                    continue
                bars = self.bars_provider(code)
                if not bars or len(bars) < 2:
                    continue
                if not has_big_yang(bars, window=3, threshold=7.0):
                    continue
                if not not_at_top(bars):
                    continue
                e = self.earnings.latest(code)
                if not passes_earnings(e):
                    continue
                last, prev = bars[-1], bars[-2]
                picks.append(Pick(code=code, theme=theme, as_of=as_of,
                                  entry_close=last.close,
                                  trigger={"last_pct": round(day_pct(prev.close, last.close), 2),
                                           "np_yoy": e.np_yoy, "rev_yoy": e.rev_yoy}))
                seen.add(code)
        return picks
```

- [ ] **Step 4: Run test, expect pass**

Run: `.venv/bin/python -m pytest tests/test_screener_run.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/app/screener/screener.py backend/tests/test_screener_run.py
git commit -m "feat(screener): Screener orchestrator combining theme+filters+earnings"
```

---

## Task 6: API endpoint GET /api/screener/picks

**Files:**
- Create: `backend/app/api/routes_screener.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_api_screener.py`

- [ ] **Step 1: Write failing test `backend/tests/test_api_screener.py`**

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
from app.screener.pool import WatchPool


def _client():
    engine = create_engine("sqlite:///:memory:", future=True,
                           connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, expire_on_commit=False, future=True)()
    WatchPool(s).add("X.SH", "算力", date(2026, 1, 2), 10.0, {"np_yoy": 25.0})
    app = create_app()
    app.dependency_overrides[get_session] = lambda: s
    return TestClient(app)


def test_list_picks():
    r = _client().get("/api/screener/picks")
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 1
    assert data[0]["code"] == "X.SH" and data[0]["theme"] == "算力"
    assert data[0]["entry_close"] == 10.0
```

- [ ] **Step 2: Run test, expect failure**

Run: `.venv/bin/python -m pytest tests/test_api_screener.py -v`
Expected: FAIL — route missing.

- [ ] **Step 3: Write `backend/app/api/routes_screener.py`**

```python
import json
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.api.deps import get_session
from app.screener.pool import WatchPool

router = APIRouter(prefix="/api/screener", tags=["screener"])


@router.get("/picks")
def picks(s: Session = Depends(get_session)):
    out = []
    for p in WatchPool(s).list():
        out.append({
            "code": p.code, "theme": p.theme,
            "first_selected_on": p.first_selected_on.isoformat(),
            "entry_close": p.entry_close, "trigger": json.loads(p.trigger or "{}"),
            "ret_t1": p.ret_t1, "ret_t3": p.ret_t3,
            "ret_t5": p.ret_t5, "ret_t10": p.ret_t10,
        })
    return out
```

- [ ] **Step 4: Add router to `backend/app/main.py`**

In `create_app`, extend the import/include block:
```python
    from app.api import routes_account, routes_trade, routes_market, routes_screener
    app.include_router(routes_account.router)
    app.include_router(routes_trade.router)
    app.include_router(routes_market.router)
    app.include_router(routes_screener.router)
```

- [ ] **Step 5: Run test, expect pass; then full suite**

Run: `.venv/bin/python -m pytest tests/test_api_screener.py -v && .venv/bin/python -m pytest -q`
Expected: target test PASS; whole suite PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/routes_screener.py backend/app/main.py backend/tests/test_api_screener.py
git commit -m "feat(api): GET /api/screener/picks over WatchPool"
```

---

## Task 7: Daily runner script

**Files:**
- Create: `backend/scripts/run_screener.py`

Thin orchestration; verified by manual run after the historical DB is populated.

- [ ] **Step 1: Write `backend/scripts/run_screener.py`**

```python
import sys
from pathlib import Path
from datetime import date

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings
from app.db.database import make_engine, make_session_factory, Base
import app.db.models  # noqa: F401
from app.data.quote_store import QuoteStore
from app.data.rate_limiter import RateLimiter
from app.screener.themes import StaticThemeSource
from app.screener.earnings import TushareEarningsSource
from app.screener.screener import Screener
from app.screener.pool import WatchPool

# Curated fallback themes (replace with TushareThemeSource if the spike confirmed
# concept access). Codes are examples; edit to the real membership.
THEMES = {
    "算力": [], "半导体芯片": [], "电力": [], "英伟达算力链": [],
}


def main():
    s = get_settings()
    engine = make_engine(); Base.metadata.create_all(engine)
    session = make_session_factory(engine)()
    store = QuoteStore(session)

    import tushare as ts
    pro = ts.pro_api(s.tushare_token)
    limiter = RateLimiter(max_calls=100, period_s=60.0)

    class LimitedEarnings(TushareEarningsSource):
        def latest(self, code):
            limiter.acquire(); return super().latest(code)

    today = date.today()

    def bars_provider(code):
        return store.get_bars(code, date(today.year - 1, today.month, today.day), today)

    sc = Screener(themes=StaticThemeSource(THEMES), earnings=LimitedEarnings(pro),
                  bars_provider=bars_provider)
    picks = sc.run(as_of=today)
    pool = WatchPool(session)
    for p in picks:
        pool.add(p.code, p.theme, p.as_of, p.entry_close, p.trigger)
        print(f"PICK {p.code} {p.theme} @ {p.entry_close}", flush=True)
    # update forward returns for all active picks
    for entry in pool.list():
        bars = store.get_bars(entry.code, entry.first_selected_on, today)
        pool.update_forward_returns(entry.code, entry.first_selected_on, bars)
    print(f"SCREENER_DONE picks={len(picks)} pool={len(pool.list())}", flush=True)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Sanity check — imports resolve**

Run (from `backend/`): `.venv/bin/python -c "import sys; sys.argv=['x']; import importlib.util as u; spec=u.spec_from_file_location('rs','scripts/run_screener.py'); m=u.module_from_spec(spec); spec.loader.exec_module(m) if False else print('import-only ok')"`

Simpler: `.venv/bin/python -c "import ast; ast.parse(open('scripts/run_screener.py').read()); print('parses ok')"`
Expected: `parses ok`.

- [ ] **Step 3: Commit**

```bash
git add backend/scripts/run_screener.py
git commit -m "feat(scripts): daily theme-screener runner (picks + forward-return update)"
```

---

## Task 8: Frontend "选股池" page

**Files:**
- Create: `frontend/src/components/PicksTable.tsx`, `frontend/src/pages/ScreenerPool.tsx`
- Modify: `frontend/src/App.tsx`

- [ ] **Step 1: Write `frontend/src/components/PicksTable.tsx`**

```tsx
type Pick = {
  code: string; theme: string; first_selected_on: string; entry_close: number;
  ret_t1: number | null; ret_t3: number | null;
  ret_t5: number | null; ret_t10: number | null;
};

function pct(v: number | null) {
  return v == null ? "-" : (v * 100).toFixed(1) + "%";
}

export function PicksTable({ picks }: { picks: Pick[] }) {
  if (!picks.length) return <p>观察池为空</p>;
  return (
    <table>
      <thead><tr>
        <th>代码</th><th>题材</th><th>入选日</th><th>入选价</th>
        <th>T+1</th><th>T+3</th><th>T+5</th><th>T+10</th>
      </tr></thead>
      <tbody>
        {picks.map((p) => (
          <tr key={p.code + p.first_selected_on}>
            <td>{p.code}</td><td>{p.theme}</td><td>{p.first_selected_on}</td>
            <td>{p.entry_close.toFixed(2)}</td>
            <td>{pct(p.ret_t1)}</td><td>{pct(p.ret_t3)}</td>
            <td>{pct(p.ret_t5)}</td><td>{pct(p.ret_t10)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
```

- [ ] **Step 2: Write `frontend/src/pages/ScreenerPool.tsx`**

```tsx
import { useEffect, useState } from "react";
import { apiGet } from "../api/client";
import { PicksTable } from "../components/PicksTable";

type Pick = {
  code: string; theme: string; first_selected_on: string; entry_close: number;
  ret_t1: number | null; ret_t3: number | null;
  ret_t5: number | null; ret_t10: number | null;
};

export function ScreenerPool() {
  const [picks, setPicks] = useState<Pick[]>([]);
  useEffect(() => {
    apiGet<Pick[]>("/api/screener/picks").then(setPicks).catch(() => {});
  }, []);
  return (
    <div style={{ padding: 24 }}>
      <h1>选股池</h1>
      <PicksTable picks={picks} />
    </div>
  );
}
```

- [ ] **Step 3: Update `frontend/src/App.tsx` to add a simple two-view switch**

```tsx
import { useState } from "react";
import { Dashboard } from "./pages/Dashboard";
import { ScreenerPool } from "./pages/ScreenerPool";

export default function App() {
  const [view, setView] = useState<"board" | "screener">("board");
  return (
    <div>
      <nav style={{ display: "flex", gap: 12, padding: 12 }}>
        <button onClick={() => setView("board")}>交易看板</button>
        <button onClick={() => setView("screener")}>选股池</button>
      </nav>
      {view === "board" ? <Dashboard /> : <ScreenerPool />}
    </div>
  );
}
```

- [ ] **Step 4: Build to verify types**

Run: `cd frontend && npm run build`
Expected: build succeeds.

- [ ] **Step 5: Commit**

```bash
git add frontend/src -- ':!frontend/node_modules'
git commit -m "feat(frontend): 选股池 page with picks + forward-return table"
```

---

## Task 9: Integration run + README

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Full backend suite**

Run (from `backend/`): `.venv/bin/python -m pytest -q`
Expected: all prior tests + new screener tests PASS.

- [ ] **Step 2: Real run (after historical DB is populated and themes are filled)**

Edit `THEMES` in `scripts/run_screener.py` with real member codes (or wire
`TushareThemeSource` if the Task 0 spike confirmed concept access). Then:

```bash
cd backend && .venv/bin/python scripts/run_screener.py
```
Expected: prints `PICK ...` lines and `SCREENER_DONE picks=N pool=M`. Verify
`GET /api/screener/picks` returns them; the "选股池" page shows the table.

- [ ] **Step 3: Add a "Theme screener" section to `README.md`**

Document the four filters, the `run_screener.py` command, the `ThemeSource`
fallback (static vs tushare concept), and that it reads the shared historical
quote DB via `QuoteStore`.

```markdown
## Theme screener & watch pool

Daily screen of hot-theme stocks (达链/半导体芯片/算力/电力) printing a >7%
bullish candle in the last 3 days, with net-profit YoY ≥20% & revenue YoY >0,
that are not extended (≤85% of 52w high & 60d return <50%). Picks enter a watch
pool tracked at T+1/3/5/10.

```bash
cd backend
.venv/bin/python scripts/run_screener.py   # after historical DB is populated
```

Themes come from `StaticThemeSource` (curated) or `TushareThemeSource` (concept
API, if your points allow). Reads bars from the shared historical quote DB via
`app/data/quote_store.py::QuoteStore`.
```

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "docs: README section for theme screener & watch pool"
```

---

## Self-Review (completed by author)

**Spec coverage:**
- Themes (达链/半导体芯片/算力/电力), tushare-or-static membership → Task 0 spike, Task 2 ✓
- Big-yang >7% green in last 3d → Task 1 `has_big_yang` ✓
- Earnings np_yoy≥20% & rev_yoy>0 → Task 3 `passes_earnings` ✓
- Not at top (≤0.85×52w-high ∧ 60d-return<50%) → Task 1 `not_at_top` ✓
- Watch pool + T+1/3/5/10 forward returns → Task 4 ✓
- Daily runner → Task 7; API → Task 6; 选股池 page → Task 8 ✓
- Shared data layer (QuoteStore) → Tasks 5/7 read via bars_provider/QuoteStore ✓

**Placeholder scan:** none. `THEMES` in Task 7 is intentionally empty with an
explicit instruction to fill real codes / wire TushareThemeSource (gated by the
spike) — documented, not a hidden TODO.

**Type consistency:** `DailyBar` fields (open/high/low/close/trade_date) used
consistently in filters/screener/pool. `Earnings(np_yoy, rev_yoy)` consistent
across earnings/screener. `Pick(code, theme, as_of, entry_close, trigger)` →
`WatchPool.add(code, theme, on, entry_close, trigger)` field-for-field. WatchPool
`ret_t1/t3/t5/t10` consistent across model, pool, API, frontend.

**Known risks (flagged):**
- Concept API gating (Task 0 spike → StaticThemeSource fallback).
- Real picks require the historical DB populated and theme membership filled.
- `not_at_top` 52w window uses available bars; with <252 bars it uses what exists
  (acceptable until the 5y backfill completes).
```
