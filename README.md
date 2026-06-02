# A-Share Trading Board

A-share market dashboard + paper-trading system. **Slice 0 + 1** delivers the
monorepo scaffold, an A-share historical data pipeline (tushare → raw OHLCV +
adj_factor), and a daily mark-to-market paper-trading account with a minimal
React dashboard.

> Status: slices 2–4 (discovery engine, TradingAgents decisions, report analysis)
> are out of scope here and built later.

## Architecture

- **Backend** — FastAPI (Python 3.11), SQLAlchemy 2.x, layered modules:
  `config` · `db` (models) · `data` (source interface + tushare adapter +
  qfq/hfq adjustment + qlib store) · `trading` (PaperBroker) · `api` (REST).
- **Frontend** — React 18 + Vite + TypeScript + ECharts.
- **Data** — qlib holds **non-adjusted OHLCV + adj_factor** (qfq/hfq derived on
  demand); application state (accounts/positions/trades/equity) in a SQL DB.
- **DB** — PostgreSQL is the documented default (`docker-compose.yml`). The local
  MVP runs on **SQLite** (no docker required) via `DATABASE_URL=sqlite:///./ashare.db`.

## Prerequisites

- Python 3.11 (qlib pins 3.11; **not** 3.13)
- A C toolchain for qlib: `apt-get install -y build-essential`
- Node.js 18+ / npm
- A tushare token (high-points level for `adj_factor`)

## Backend setup

```bash
cd backend
python3.11 -m venv .venv
.venv/bin/pip install -U pip
.venv/bin/pip install pyqlib tushare scrapling   # qlib needs build-essential
.venv/bin/pip install -e ".[dev]"                # project + test deps

cp .env.example .env        # then edit: set TUSHARE_TOKEN, DATABASE_URL, ...
.venv/bin/python scripts/init_db.py     # create tables
.venv/bin/python scripts/seed_account.py # seed the "main" account (INITIAL_CASH)
.venv/bin/uvicorn app.main:app --reload --port 8000
```

Health check: `curl localhost:8000/api/health` → `{"status":"ok"}`.

### Environment (`backend/.env`)

| key | meaning |
|---|---|
| `DATABASE_URL` | `sqlite:///./ashare.db` (MVP) or `postgresql+psycopg2://…` |
| `TUSHARE_TOKEN` | tushare pro token (kept out of git) |
| `DEEPSEEK_API_KEY` / `DEEPSEEK_BASE_URL` / `DEEPSEEK_MODEL` | LLM (slice 3) |
| `QLIB_DATA_DIR` | qlib data dir (default `./data/qlib_cn`) |
| `INITIAL_CASH` | starting paper cash (default 1,000,000) |

## Frontend setup

```bash
cd frontend
npm install
npm run dev        # http://localhost:5173  (talks to backend on :8000)
npm run build      # production build + type-check
```

Set `VITE_API_BASE` to point at a non-default backend URL.

## Historical data backfill

```bash
cd backend
# pull non-adjusted daily bars + adj_factor into per-instrument CSVs
.venv/bin/python scripts/backfill_history.py --codes 600519.SH 000001.SZ --start 20240101
# incremental recent update
.venv/bin/python scripts/daily_update.py --codes 600519.SH 000001.SZ --days 5
```

CSVs land under `backend/data/qlib_cn/csv/` with columns
`date,open,high,low,close,volume,factor`.

> **qlib `dump_bin`** (CSV → qlib binary) is **not** shipped in the pyqlib pip
> package; fetch `scripts/dump_bin.py` from the qlib GitHub repo when the
> qlib-backed price provider is built. Not required for the MVP (price provider is
> a placeholder). See `docs/superpowers/plans/spike-notes.md`.

## Historical quote database

Whole-market ~5y daily history in `daily_quotes` (raw OHLCV + adj_factor +
daily_basic metrics), with an `ingested_days` progress gate.

```bash
cd backend
# resumable, rate-limited (<=100 tushare calls/min); just rerun to resume
.venv/bin/python scripts/backfill_quotes.py --start 20210101 --max-per-min 100
# daily incremental update
.venv/bin/python scripts/daily_update_quotes.py --days 7
```

Resumable + idempotent: each trade date is fetched whole-market
(`daily` + `daily_basic` + `adj_factor`), upserted, then marked ingested; a
killed run continues from the break point on rerun. Read via
`app/data/quote_store.py::QuoteStore` (returns `DailyBar`s; apply
`to_qfq`/`to_hfq` from `app/data/adjust.py`). The discovery engine reads from
this DB instead of fetching tushare at scan time.

## Running tests

```bash
cd backend
.venv/bin/python -m pytest -q     # 29 tests
```

## Key design constraints

- Store **raw OHLCV + adj_factor**; derive qfq/hfq (`hfq = raw*factor`,
  `qfq = raw*factor/latest_factor`). Volume is never adjusted.
- Equity is **marked-to-market daily**; trading decisions (slice 3) are weekly.
- BUY/SELL update positions with weighted-average cost; insufficient
  cash/shares are rejected.
