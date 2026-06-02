# Theme Screener & Watch Pool — Design Spec

Date: 2026-06-02. Separate project from the trading board, **sharing the data
layer** (`app/data`, historical quote DB / `QuoteStore`). Lives in the same repo
as a self-contained module `backend/app/screener/`.

## Goal

Daily-screen A-share **hot-theme** stocks (NVIDIA compute supply chain "达链",
semiconductor/chip, compute power, electric power) for ones that **recently
printed a big bullish candle, have strong earnings, carry a concept, and are not
extended** — then **track each pick's forward returns** so the strategy's hit
rate is measurable over time.

## Decisions (locked)

- **Themes:** NVIDIA compute supply chain (达链), 半导体/芯片, 算力, 电力 (A-shares).
- **Theme membership:** tushare concept/industry API (auto). Spike first to confirm
  the user's points expose concept members; fall back to a manual per-theme list.
- **Big yang candle:** single-day **pct_chg > 7%** AND close > open, occurring in
  the **last 3 trading days**.
- **Earnings:** latest report **net-profit YoY growth ≥ 20%** AND revenue YoY > 0.
- **Not at top (both):** price ≤ 52-week-high × 0.85 (≥15% below the high) AND
  60-day cumulative return < 50%.
- **Tracking:** daily screen → new picks enter a **watch pool** (entry date +
  entry close) → forward returns T+1/T+3/T+5/T+10 updated daily.
- **Organization:** same repo, new `app/screener/` module reusing `app/data`.

## Architecture

New module `backend/app/screener/`, reusing `app/data` (`QuoteStore`, adjustment).

- **`ThemeUniverse`** — resolves each theme → member stock codes via a
  `ThemeSource` interface. Default impl: tushare concept/industry; fallback impl:
  a static curated dict. Returns `{theme: [codes]}`.
- **`EarningsSource`** (interface) — latest net-profit YoY and revenue YoY per
  code (tushare `fina_indicator`/income). Mocked in tests.
- **`Screener`** — for each theme member, apply the four filters using
  `QuoteStore` bars + `EarningsSource`; emit qualifying picks with the trigger
  detail (which day was the big yang, earnings numbers, distance-from-high).
- **`WatchPool`** — persist new picks (idempotent on (code, first_selected_on));
  recompute forward returns for all active picks from `QuoteStore`.

### Data flow

```
ThemeUniverse (themes -> member codes)
  -> Screener (QuoteStore bars + EarningsSource): big-yang ∧ earnings ∧ not-top
  -> WatchPool.add(new picks)            # entry date + entry close + trigger detail
  -> WatchPool.update_forward_returns()  # T+1/3/5/10 vs entry, from QuoteStore
  -> GET /api/screener/picks -> "选股池" page
```

## Filters (all must pass)

1. **Theme:** code is a member of a target theme.
2. **Big yang:** any of the last 3 trading days has `pct_chg > 7%` and close > open.
3. **Earnings:** latest report net-profit YoY ≥ 20% and revenue YoY > 0.
4. **Not at top:** close ≤ 0.85 × max(high, trailing 52 weeks) AND 60-day return < 50%.

## Data model

### `watch_pool` (PK = (code, first_selected_on))

- `code`, `theme`, `first_selected_on` (date), `entry_close` (float)
- `trigger` (JSON): big-yang date & pct, net-profit YoY, revenue YoY, pct-below-52w-high, 60d return
- forward returns: `ret_t1, ret_t3, ret_t5, ret_t10` (float, nullable until the day arrives)
- `last_updated` (date)

A pick is recorded once (first qualifying day); forward returns fill in as
trading days pass.

## API

- **`GET /api/screener/picks`** — all pool entries with theme, entry date/price,
  trigger detail, and T+1/3/5/10 returns. Optional `?theme=` / `?since=` filters.

## Runner

- **`scripts/run_screener.py`** — daily after close: run `Screener` over theme
  members, `WatchPool.add` new picks, `WatchPool.update_forward_returns`. Thin
  orchestration over tested units; reuses the rate limiter for any tushare calls.

## Frontend

- A **"选股池"** page: table of picks — code, theme, entry date, entry price, and
  T+1/3/5/10 returns (color-coded). Reuses the existing `apiGet` client.

## Testing strategy (TDD)

- **Pure logic (unit, fake bars):**
  - big-yang detection over a 3-day window (boundary: exactly 7% fails, >7% passes;
    close>open required);
  - not-at-top (52w-high distance + 60d return), both-must-hold;
  - forward-return computation (T+N vs entry close; null before the day exists);
  - `WatchPool` idempotent add (same code+date twice → one row) and return updates.
- **Theme membership + earnings:** behind `ThemeSource`/`EarningsSource`
  interfaces, **mocked** in tests.
- **Integration:** a real run against tushare (themes + a few picks), detached.

## Risks

- **tushare concept API may be gated by points** — Task 0 spike verifies it;
  fallback is a manual curated theme→codes dict (the `ThemeSource` interface makes
  this a drop-in swap).
- Earnings endpoint likewise verified in the spike.

## Shared dependencies

Reads the historical quote DB via `app/data/quote_store.py::QuoteStore` (raw bars
+ adjustment). No duplication of the data layer; the screener is a consumer.
