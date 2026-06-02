# Historical Quote Database — Design Spec

Date: 2026-06-02. Builds on slice 0+1 (data layer + DailyBar + tushare adapter).
Prerequisite for slice 2 (discovery engine) and future backtesting.

## Goal

A queryable **whole-market A-share daily history** stored in SQL: ~5 years of
**raw OHLCV + adj_factor + daily_basic metrics** for every stock, populated by a
**resumable, idempotent, rate-limited** tushare backfill, with a daily
incremental update and a read interface that returns `DailyBar`s.

## Decisions (locked)

- **Storage:** SQL table (SQLite for MVP / PostgreSQL later) — not qlib bin / Parquet.
- **Depth:** ~5 years of history.
- **Universe:** whole A-share market (fetch by trade date → all stocks that traded).
- **Columns:** raw OHLCV + adj_factor **plus** daily_basic metrics
  (turnover_rate, volume_ratio, circ_mv, total_mv, pe, pb).
- **Robustness:** resumable + idempotent (per-trade-date), survives interruption.
- **Rate limit:** **≤ 100 tushare calls per minute** (hard constraint).
- **Adjustment:** store **raw prices only** + adj_factor; derive qfq/hfq on read
  (reuse slice-1 `app/data/adjust.py`).

## Data model

### `daily_quotes` (wide table; PK = (code, trade_date))

- Quote: `open, high, low, close, pre_close, vol, amount, adj_factor`
- Metrics (daily_basic): `turnover_rate, volume_ratio, circ_mv, total_mv, pe, pb`
- Index on `trade_date` (whole-market scans) and PK on `(code, trade_date)`.

Nullable metric columns (daily_basic may miss some rows); missing adj_factor
defaults to 1.0 (slice-1 convention).

### `ingested_days` (PK = trade_date)

Marks a trade date as **fully ingested**. Drives resume (calendar − ingested)
and idempotency. A date is inserted here only after its quotes are committed.

## Backfill (`scripts/backfill_quotes.py`)

1. Pull the **trading calendar** (`trade_cal`) for the 5-year window → trade dates.
2. For each date **not** in `ingested_days` (ascending):
   - `daily(trade_date=…)` → whole-market OHLCV + pct_chg
   - `daily_basic(trade_date=…)` → whole-market metrics
   - `adj_factor(trade_date=…)` → whole-market factors
   - Merge the three on `ts_code`; **upsert** rows into `daily_quotes`
     (insert-or-replace on (code, trade_date) → idempotent).
   - Insert the date into `ingested_days`.
3. **Resumable:** already-ingested dates are skipped; rerun continues from the
   break point; reruns never duplicate (upsert + ingested gate).
4. **Rate limiter:** a throttle guarantees **≤ 100 calls/min** (e.g. token bucket
   or min spacing ≈ 0.6s between calls; or 100-then-wait-to-minute). All three
   per-day calls pass through it. Retries on tushare rate/transient errors with
   backoff (failure on a date leaves it un-ingested → retried next run).
5. **Execution:** run **detached via `setsid`** with a log; a lightweight
   background watcher polls for completion (lesson from prior killed jobs).
   Estimated ~3,750 calls (1,250 days × 3) ÷ 100/min ≈ **~40 min**.

## Incremental update (`scripts/daily_update_quotes.py`)

Same core as backfill: pull the latest trade date(s) absent from `ingested_days`
and upsert. Run after daily close. Reuses the rate limiter and ingest gate.

## Read interface (`app/data/quote_store.py`)

- `QuoteStore.get_bars(code, start, end) -> list[DailyBar]` — reads `daily_quotes`,
  returns slice-1 `DailyBar`s (raw prices + adj_factor); callers apply
  `to_qfq`/`to_hfq` as needed.
- `QuoteStore.get_market_on(trade_date) -> list[row]` — whole-market rows for a
  date (feeds the discovery engine's MomentumProvider).
- Discovery engine and backtest read from the DB via this interface — **no more
  ad-hoc tushare fetches** at scan time.
- Optional later: `GET /api/bars/{code}` for front-end K-line.

## Testing strategy (TDD)

- **Pure logic (unit, fake data):**
  - merge of daily + daily_basic + adj_factor into a `daily_quotes` row;
  - **idempotent upsert** (ingest same date twice → no duplicate rows);
  - **resume** (dates in `ingested_days` are skipped);
  - rate limiter (N calls never exceed 100 in any 60s window — test with a fake clock);
  - `QuoteStore.get_bars` → `DailyBar` mapping and adjustment hand-off.
- **tushare whole-market fetch:** behind the existing source interface, **mocked**.
- **Integration:** the real 5-year backfill — detached run against the token,
  not a unit test.

## Constraints honored

- Raw prices + adj_factor only; qfq/hfq derived (project data-correctness rule).
- ≤ 100 tushare calls/min.
- Idempotent + resumable (survives the harness killing long jobs).
- External data isolated behind interfaces; pure logic TDD-first.
- SQLite now, PostgreSQL-compatible schema for later swap.
