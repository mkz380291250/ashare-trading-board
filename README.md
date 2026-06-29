# A-Share Trading Board

A-share market dashboard + paper-trading system. Covers the full stack: A-share
historical data pipeline (tushare → raw OHLCV + adj_factor), a daily
mark-to-market paper-trading account with a React dashboard, a whole-market
discovery engine, a multi-agent decision engine, research-sentiment signals,
a qlib backtest/factor-analysis layer, and a **fully automated paper-trading
closed loop**(因子选股 → AI 辩论 → 自动执行 → 归因 → 策略闸;见下方「全自动纸面闭环」).

> Status: slices 0–5 built. The closed loop runs daily via a scheduler daemon
> (北京时间 22:00) and is paper-only (virtual cash, no live trading).

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
- 手动跑全套更新(`daily_full.py`,现为 8 步全链:全市场行情入库 → qlib 重建 →
  跟踪表指标刷新 → 因子选候选 → AI 辩论决策+自动执行 → 盯市 → 归因 → 策略闸,详见
  下方「全自动纸面闭环」):

  ```bash
  .venv/bin/python scripts/daily_full.py
  ```

- 自动调度(线上实际方案):本机 bash 守护进程 `scripts/daily_scheduler_daemon.sh`,
  每个交易日(周一~周五)**北京时间 22:00(= 09:30… 现为 14:00 UTC)** 跑一次
  `daily_full.py`,不依赖后端常驻。用 `setsid` 脱离会话启动,容器重启后需重新拉起:

  ```bash
  setsid bash scripts/daily_scheduler_daemon.sh >/tmp/ashare_sched.out 2>&1 &
  # pid 写在 /tmp/ashare_daily_sched.pid;日志 /tmp/ashare_daily_sched.log
  ```

  > 改了触发时间后必须**杀旧守护进程重新拉起**(运行中的 bash 已把循环体读进内存,
  > 不重启不生效)。

- 进程看门狗:仓库根的 `HEARTBEAT.md` 配了一个任务,定期 `kill -0` 探活守护进程,
  死了(或容器重启带走了)就自动重新 `setsid` 拉起。

- 后端进程内 APScheduler(`app/scheduler.py`,`ENABLE_SCHEDULER=true` 开启)仍保留,
  作为后端常驻时的备用触发;线上主用上面的 bash 守护进程。

## 全自动纸面闭环 (closed loop)

把原来的开环流水线(选股 → 人工看 → 人工审批下单)升级成**全自动纸面闭环**,每个
交易日由调度守护进程一次跑完。链路:**qlib 因子选股 → AI 辩论决策 → 自动执行
(PaperBroker)→ 前向归因 → 策略闸**。仍是纯纸面、虚拟资金,不接实盘。

`scripts/daily_full.py::run_all` 顺序执行 8 步,单步失败不阻断整链:

1. `step_quotes` — 全市场当日行情入库
2. `step_qlib` — qlib 数据重建(CSV → dump_bin)
3. `step_tracklist` — 跟踪表指标刷新
4. `step_select` — 用**冻结因子集**对全市场打分,有界迭代选出进辩论的候选
   (持仓必辩 + 按复合分填空位到目标仓位 15,质量门槛全市场前 30%,单日上限 32,不强买)
5. `step_debate` — 多智能体辩论;BUY/SELL **置信度 ≥0.6 即自动纸面下单**,低于阈值标
   `LOW_CONF` 不下单;风险态(risk-off)时只辩持仓、停止买入
6. `step_mark` — 当日盯市(按 account_id + as_of 幂等)
7. `step_attribution` — 写决策后向收益(T+1/3/5/10、以 T+5 定 hit)与每日因子 IC/RankIC
8. `step_policy` — 阈值触发自动动作,全部过护栏审计(可审计 / 可回滚 / 留旧产物)

### 选股:冻结因子集

qlib 复合因子**完全替代**了原 MomentumProvider。定期重挖产出
`data/factors/frozen_composite.json`(只存因子名、不存表达式),每日只按冻结集打分。

```bash
cd backend
.venv/bin/python scripts/freeze_factors.py          # 重挖并冻结(产出 frozen_composite.json)
.venv/bin/python scripts/run_discovery.py --source qlib   # 默认即 qlib,写全市场全量排名
```

### 归因度量层 (`app/attribution/`)

无前向偏差(窗口未走完不写),作为策略闸的可信输入。两张表:
`decision_outcomes`(决策后向收益 + hit)、`factor_ic_daily`(每日 IC/RankIC)。

### 策略闸 (`app/policy/`) — 三个自动动作

纯检测(`rules.py`)→ 统一过护栏(`guardrails.py`,审计落 `policy_actions` 表,幂等)
→ 执行动作(`actions.py`)。默认阈值(实测可调,见 `app/config.py`):

- **因子衰减**:20 日滚动 RankIC 连续 5 日 < 0.02 → **自动重挖换产物**(旧产物归档
  `data/factors/archive/`,可回滚)
- **风险熔断**:当前回撤 > 20% 或近 30 日胜率 < 40% → **自动停买**(下一日只辩持仓)
- **弱持仓**:持仓复合分连续 3 日跌出全市场前 50% → **自动标卖**

### 运行状态(看板可见,不发微信)

`run_all` 每次把这次运行落 `scheduler_runs` 表(起止时间 / 成功失败 / 各步明细 JSON)。
看板「闭环健康」卡片底部显示「上次自动运行:时间 + 成功 / 失败:哪一步」,失败标红。

### 闭环相关接口

- `GET /api/attribution/hit-rate?window=30` — 近窗命中率 + 样本数
- `GET /api/attribution/forward-ic?days=60` — 每日 IC/RankIC 序列(喂折线图)
- `GET /api/policy/actions?limit=50` — 策略动作审计(时间倒序)
- `GET /api/health/last-run` — 最近一次自动运行状态(无运行返回 `null`)
- `GET /api/equity/{id}` 每点带 `drawdown`;`GET /api/decisions` 带复合分/置信度

前端对应:**策略闸** `/policy`、**归因** `/attribution` 两个新页(导航「更多」里),
Dashboard 顶部「闭环健康」面板,净值图叠加回撤,决策页加复合分/置信度列。

## Running tests

```bash
cd backend
.venv/bin/python -m pytest -q     # 后端 ~319 tests(含闭环:归因/策略闸/调度状态)

cd ../frontend
npx vitest run                    # 前端 ~50 tests
```

## Key design constraints

- Store **raw OHLCV + adj_factor**; derive qfq/hfq (`hfq = raw*factor`,
  `qfq = raw*factor/latest_factor`). Volume is never adjusted.
- Equity is **marked-to-market daily**; trading decisions (slice 3) are weekly.
- BUY/SELL update positions with weighted-average cost; insufficient
  cash/shares are rejected.
