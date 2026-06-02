# Slice 2: Discovery Engine — Design Spec

Date: 2026-06-02. Builds on slice 0+1 (backend data layer + paper trading).

## Goal

A daily **opportunity discovery engine** that scans the whole A-share market,
scores every stock on **price/volume momentum** signals, and surfaces the
**Top-8** candidates ("机会榜"). Designed around a **pluggable `SignalProvider`**
so later qualitative signals (slice 4: scrapling + DeepSeek) and money-flow
signals slot in without rework.

Priority context: 机会发现 (热点/龙头/爆发候选) is the 2nd priority after paper
trading. Top-N is capped at **8** to control downstream API/LLM cost.

## Scope (slice 2)

- One signal provider: **`MomentumProvider`** (量价动量).
- Whole-market scan via tushare (single whole-market call per trade date).
- Weighted-normalized-sum scorer → rank → Top-8.
- Persist daily Top-8; REST endpoint; dashboard panel.
- **Out of scope:** money-flow / technical-pattern / fundamental providers
  (later providers), WeChat push (slice 5), TradingAgents decisions (slice 3).

## Architecture

New module `backend/app/discovery/`, parallel to `data/` and `trading/`.

### Core abstractions

- **`SignalProvider`** (ABC) — `compute(market: MarketSnapshot) -> dict[str, float]`:
  given one trade date's whole-market data, return `{code: raw_factor_value}`.
  Pluggable; every future signal source implements this.
  - A provider that emits multiple sub-factors registers as multiple logical
    factors (see `MomentumProvider`).
- **`MomentumProvider`** — first implementation. Emits 4 sub-factors per stock
  (each treated as an independent factor in scoring):
  1. **mom_5d** — 5-day cumulative return (momentum strength)
  2. **turnover** — turnover_rate (activity)
  3. **vol_ratio** — volume_ratio (volume surge)
  4. **breakout** — close / 20-day-high (proximity to new high; →1 = breaking out)
- **`DiscoveryScorer`** — combines factors:
  1. **Normalize** each factor cross-sectionally to a **percentile rank in [0,1]**
     (robust to scale/outliers; ties share the mean percentile).
  2. **Weighted sum** with configurable weights (default equal 25% each) → total score.
  3. **Sort** descending, **truncate to Top-N (=8)**.
  Output: ordered list of `(code, score, {factor: raw_value})`.
- **`DiscoveryRunner`** — orchestration: fetch market snapshot → run providers →
  scorer → persist Top-8 for the trade date.

### Data flow

```
tushare daily + daily_basic (whole market, 1 trade date)
  -> MarketSnapshot (per-code rows)
  -> MomentumProvider.compute() -> 4 factor maps
  -> DiscoveryScorer (percentile-normalize -> weighted sum -> rank -> Top-8)
  -> persist discovery_picks rows
  -> GET /api/discovery -> dashboard "机会榜" panel
```

### Market data fetch

- `daily(trade_date=YYYYMMDD)` → whole market: ts_code, close, pct_chg, vol, ...
- `daily_basic(trade_date=YYYYMMDD)` → whole market: ts_code, turnover_rate, volume_ratio, ...
- For **mom_5d** and **breakout**, need a short trailing window (≈25 calendar days)
  of closes per stock. Fetch by trade_date across the window (a handful of
  whole-market calls), or reuse qlib once a qlib-backed store exists. Slice 2
  fetches the window via tushare by trade_date; isolated behind a
  `MarketHistory` interface so a qlib-backed impl can replace it later.
- All tushare access sits behind interfaces and is **mocked in unit tests**.

## Data model

New table **`discovery_picks`** (one batch of 8 rows per trade date):

| column | type | notes |
|---|---|---|
| id | int PK | |
| as_of | date | trade date of the scan |
| code | str(16) | stock code |
| rank | int | 1..8 |
| score | float | total weighted-normalized score |
| factors | str (JSON) | raw sub-factor values, for "why selected" / signal backtest |

Indexed by `as_of`. History is queryable per date.

## API

- **`GET /api/discovery`** — latest batch (most recent `as_of`), Top-8 ordered by rank.
- **`GET /api/discovery?date=YYYY-MM-DD`** — historical batch for that date.
- Response items: `{as_of, code, rank, score, factors}`.

## Runner

- **`scripts/run_discovery.py`** — run after daily close: pull snapshot, score,
  upsert `discovery_picks` for the date. Thin orchestration over tested units;
  verified by a real manual run against the tushare token.

## Frontend

- Dashboard gains a **"机会榜 Top-8"** panel: list of code / rank / score;
  expandable row reveals the sub-factor raw values. Reuses the existing
  `apiGet` client and table styling.

## Testing strategy

TDD, following slice 0+1:

- **Pure logic (primary, unit-tested with fake data):**
  - `DiscoveryScorer`: percentile normalization, weighted sum, descending sort,
    Top-8 truncation, tie handling, fewer-than-8 stocks edge case.
  - `MomentumProvider`: each sub-factor's math (5d return, breakout ratio, etc.)
    from a small fixture market.
- **tushare whole-market fetch / MarketHistory:** behind an interface, mocked
  in tests (same pattern as slice 1's `TushareSource`).
- **API:** `/api/discovery` over an in-memory sqlite DB with seeded picks
  (StaticPool + check_same_thread=False, per slice 1 lesson).
- **Runner:** integration — manual real-data run, not a unit test.

## Configuration

- Factor weights configurable (default equal). Top-N default 8. Trailing window
  length (default ~20 trading days for breakout/momentum). Universe defaults to
  full A-share; optionally restrictable to an index member list later.

## Key constraints honored

- Pluggable `SignalProvider` — slice 4 qualitative signal slots in as another provider.
- Top-N = 8 to cap downstream cost.
- Daily cadence (aligns with daily settlement); decisions remain weekly (slice 3).
- All external data isolated behind interfaces; pure logic is TDD-first.
