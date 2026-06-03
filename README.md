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

## Discovery engine (机会榜)

Daily whole-market scan scoring price/volume momentum — mom_5d (5-day return),
turnover (turnover_rate), vol_ratio (量比, computed as today's volume ÷ prior-5-day
average since tushare's historical `volume_ratio` is null), and breakout
(close ÷ 20-day high). Each factor is percentile-normalized, equal-weighted, and
the Top-8 are persisted to `discovery_picks`. Reads the historical quote DB via
`QuoteStore` (no tushare at scan time).

```bash
cd backend
.venv/bin/python scripts/run_discovery.py            # latest date in DB
.venv/bin/python scripts/run_discovery.py --date 2026-05-29
```

Surfaced at `GET /api/discovery` (latest, or `?date=YYYY-MM-DD`) and the dashboard
机会榜 panel. Pluggable `SignalProvider` — slice-4 qualitative / money-flow signals
slot in as more providers without rework.

## Decision engine (multi-agent, slice 3)

Weekly multi-agent debate (量价/基本面 analysts → 多空 researchers → trader →
risk committee) over holdings ∪ discovery Top-8, producing BUY/SELL/HOLD with full
reasoning. The LLM is pluggable — default **local Claude** (headless `claude -p`),
or DeepSeek (`DECISION_LLM=deepseek`). Each agent ends with a JSON verdict that the
orchestrator parses; decisions are **PENDING** until approved in the UI, which
executes the PaperBroker.

```bash
cd backend
.venv/bin/python scripts/run_decisions.py     # default local Claude (slow, nested)
DECISION_LLM=deepseek .venv/bin/python scripts/run_decisions.py
```

Surfaced at `GET /api/decisions`, `POST /api/decisions/{id}/approve|reject`, and the
dashboard 决策 panel. The 研报/新闻 analyst is a stub fed empty until slice 4 wires
scraped research reports.

## Theme screener & watch pool

Separate feature (module `app/screener/`) that **shares the data layer**. Daily
screen of hot-theme stocks (英伟达算力链 / 半导体芯片 / 算力 / 电力) that:
printed a **>7% bullish candle** in the last 3 trading days, have **net-profit
YoY ≥20% & revenue YoY >0**, and are **not extended** (≤85% of the 52-week high
AND 60-day return <50%). Picks enter a **watch pool** tracked at T+1/3/5/10.

```bash
cd backend
.venv/bin/python scripts/run_screener.py   # after the historical DB is populated
```

Themes resolve from tushare concept indices (`ths_index`/`ths_member`) by keyword
(fallback: `StaticThemeSource` curated lists). Earnings from `fina_indicator`.
Bars come from the shared historical quote DB via `QuoteStore`. Results surface at
`GET /api/screener/picks` and the frontend **选股池** tab.

## Research analysis (研报情绪信号, slice 4)

Module `app/research/`. Digests broker research and per-stock news into a
structured **research note** (`sentiment` -1..1, `rating_consensus`, `summary`)
cached in `research_notes`, feeding two consumers:

1. **Discovery** — `ResearchSignalProvider` exposes `research_sent` as a pluggable
   qualitative factor. The scorer fills missing factors with a neutral 0.5, so a
   sparse signal (only the candidate universe is analyzed) boosts covered stocks
   without penalizing the rest. Enable with `run_discovery.py --with-research`.
2. **Decision** — the brief gains a 研报观点 section that the 新闻研报分析师 reads.

Sources (`CompositeSource`, fault-isolated, dedup by title+text):
- **tushare `report_rc`** — broker ratings/target prices, per-stock & structured.
  Capped to the most recent `max_items` within `recent_days`. ⚠️ `report_rc` is
  rate-limited to **1 call/min** on standard tiers — set `RESEARCH_MAX_PER_MIN=1`
  (or your tier's limit) so a universe of N stocks paces correctly. tushare's
  `news` feed is market-wide (not per-stock) and is intentionally **not** used.
- **EastMoney** `search-api-web` JSONP — per-stock news (title/content/date).
  Container egress verified reachable 2026-06-03. On block it degrades to `[]`.

LLM is configurable via `RESEARCH_LLM` (`local` | `deepseek`), **default local
Claude** (`claude -p`, same as the decision engine). Note: the DeepSeek key must
be a real key — the committed `.env` placeholder returns 401.

```bash
cd backend
RESEARCH_MAX_PER_MIN=1 .venv/bin/python scripts/run_research.py   # holdings ∪ discovery Top8 ∪ watch pool
```

Surfaced at `GET /api/research/{code}`.

## Backtest & factor analysis (qlib, slice 5)

Module `app/backtest/`. Validates the live signals with **qlib's native engine**,
benchmarked against **沪深300**. Reuses `MomentumProvider`/`DiscoveryScorer`
(via `score_all`, no logic rewrite); signal logic is never duplicated.

Pipeline:
1. **Build qlib data** (one-time, heavy): QuoteStore → per-instrument CSV → qlib
   `dump_bin` → `data/qlib_cn`. Codes map to qlib symbols (`600519.SH`↔`SH600519`).
   沪深300 (`tushare index_daily 000300.SH`) is dumped as instrument `SH000300`.
   `dump_bin.py` is vendored from qlib v0.9.7 under `scripts/vendor/` (not in pip).
   ```bash
   cd backend
   .venv/bin/python scripts/build_qlib_data.py            # whole market (setsid; slow)
   .venv/bin/python scripts/build_qlib_data.py --limit 30 # smoke subset
   ```
2. **Backtest**: `build_score_frame` runs the scorer per day → score frame; fed to
   qlib `TopkDropoutStrategy` + backtest (`benchmark="SH000300"`, A-share costs) →
   annualized return / information ratio / max drawdown. Plus `factor_report`:
   per-day IC / RankIC (+IR) and N-layer forward returns (self-computed, qlib-free).
   ```bash
   .venv/bin/python scripts/run_backtest.py --qlib-dir ./data/qlib_cn
   ```
   ⚠️ qlib settles next-day, so the backtest end date must be **≥1 trading day
   before** the qlib calendar's last day (default `end` already leaves the buffer).

Smoke-verified on 30 stocks + 沪深300 (2026-06-03): dump/init OK, factor IC ~0.07
with monotonic layered returns, strategy metrics vs 沪深300 produced.

## 跟踪表 + 每日定时更新

- 前端「跟踪」页:粘贴同花顺自选页文本即可加入跟踪,系统自动识别 6 位代码与名称,
  展示 T+1/3/5/10、至今涨跌、最大涨幅、最大回撤。
- 接口:`POST /api/track`(body `{text}`)、`GET /api/track`、
  `DELETE /api/track/{code}/{added_on}`。
- 手动跑全套更新(依次:全市场行情入库 → qlib 重建 → 跟踪表指标刷新):

  ```bash
  .venv/bin/python scripts/daily_full.py
  ```

- 自动调度:后端进程内置 APScheduler,每天 16:00(北京时间 / Asia/Shanghai)触发
  `daily_full`。默认关闭,需在 `.env` 中开启(需后端进程常驻):

  ```
  ENABLE_SCHEDULER=true
  # 可选,覆盖默认触发时间
  DAILY_UPDATE_HOUR=16
  DAILY_UPDATE_MINUTE=0
  ```

## Running tests

```bash
cd backend
.venv/bin/python -m pytest -q     # 124 tests (board + screener + research + backtest)
```

## Key design constraints

- Store **raw OHLCV + adj_factor**; derive qfq/hfq (`hfq = raw*factor`,
  `qfq = raw*factor/latest_factor`). Volume is never adjusted.
- Equity is **marked-to-market daily**; trading decisions (slice 3) are weekly.
- BUY/SELL update positions with weighted-average cost; insufficient
  cash/shares are rejected.
