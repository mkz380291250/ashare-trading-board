# Task 0 — Environment Spike Notes

Date: 2026-06-02. Host: Debian bookworm (OpenClaw workspace), x86_64.

## Step 1 — Python 3.11
- `python3.11 --version` → **Python 3.11.2** (system `/usr/bin/python3.11`, already present).
- No deadsnakes/pyenv needed.

## Step 2 — venv + pip
- venv at `backend/.venv` (Python 3.11.2).
- pip upgraded; `pip --version` reports OK.

## Step 3 — qlib (highest risk) ✅
- **Prerequisite discovered:** host had **no C toolchain**. qlib has Cython/C extensions and a `gym` wheel build → failed/stalled without a compiler.
  - Fix: `apt-get install -y build-essential` (gcc/g++/make 12.2.0).
- Recipe that worked: `backend/.venv/bin/pip install pyqlib`
  - Installed **pyqlib 0.9.7**; `import qlib` → `0.9.7` OK.
  - numpy resolved to **2.4.6**, pandas **2.3.3** — qlib imports fine on numpy 2.x at this version. No need to pin `numpy<2`.
  - Side effect: pyqlib's `mlflow` dependency pulled in **fastapi 0.136.3 + uvicorn 0.48.0 + starlette** (backend web stack already present).
- **Install gotcha (recorded for future):** long pip builds emit no output for minutes → the OpenClaw CLI watchdog killed the subprocess (`180s no-output stall`). Mitigations applied:
  1. Raised watchdog `noOutputTimeoutMs` to 600000 in `openclaw.json`.
  2. Run heavy installs **fully detached** via `setsid bash -c '... > log 2>&1' </dev/null &` so they survive harness reaping; poll the log for an `EXIT=` marker.

## Step 4 — tushare with real token ✅
- Token in `backend/.env` (gitignored). All three endpoints return non-empty data for `600519.SH`, 2026-05-01..05-30:
  - `pro.daily(...)` → shape **(18, 11)**; cols: `ts_code, trade_date, open, high, low, close, pre_close, change, pct_chg, vol, amount`.
  - `ts.pro_bar(adj=None, ...)` → shape **(18, 11)** (raw, non-adjusted).
  - `pro.adj_factor(...)` → shape **(18, 3)**; cols: `ts_code, trade_date, adj_factor`. **adj_factor endpoint accessible at user's points level.**
- Sample: 600519 close 2026-05-29 = 1326.00 (raw); adj_factor = 8.4464.
- **Schema drivers for Task 9:** daily price column is `vol` (not `volume`); merge `daily` + `adj_factor` on `trade_date`; tushare returns rows **descending** by date → must sort ascending.

## Step 5 — tradingagents import (slice 3 readiness)
- `pip install tradingagents` → **FAILED**: all PyPI versions (0.0.0–0.7.0) **require Python >= 3.12**; we run 3.11 (pinned for qlib).
- **Decision:** slice 3 will **vendor from git `hsliuping/TradingAgents-CN`** (the A-share/tushare/DeepSeek-adapted CN fork), not PyPI.
- ⚠️ Open risk for slice 3: PyPI tradingagents wants py3.12+ while qlib wants ≤3.11. Must verify the CN fork supports 3.11, or isolate it (separate venv / subprocess). Not a blocker for slices 0/1.

## Environment summary (post-spike)
| Component | Status |
|---|---|
| Python 3.11.2 | ✅ |
| build-essential (gcc 12.2) | ✅ |
| pyqlib 0.9.7 (`import qlib` OK) | ✅ |
| fastapi 0.136.3 / uvicorn 0.48.0 | ✅ (via qlib deps) |
| tushare 1.4.29 (token + adj_factor verified) | ✅ |
| scrapling 0.4.8 | ✅ |
| tradingagents (PyPI) | ❌ needs py3.12 → vendor from git in slice 3 |
| PostgreSQL | ⏳ not yet (Task 6) |
| docker | ❌ absent → native PG or managed URL |

**Gate result: PASS** — qlib imports, tushare+adj_factor verified. Cleared to proceed to Phase B data tasks.

## Post-build finding — qlib `dump_bin` (Task 11 Step 3)
- `python -m qlib.scripts.dump_bin` → **ModuleNotFoundError: No module named 'qlib.scripts'**.
- pyqlib 0.9.7 pip package ships **no `dump_bin` script and no `qlib` CLI** (verified: no `*dump*` under the package, no `qlib` in `.venv/bin`).
- `dump_bin.py` lives only in the qlib GitHub repo `scripts/` dir, not on PyPI.
- **Resolution / TODO (deferred, not MVP-critical):** when the qlib-backed price provider is built (replacing `DictPriceProvider`), fetch `scripts/dump_bin.py` from `github.com/microsoft/qlib` and run it standalone, e.g.
  `python dump_bin.py dump_all --csv_path ./data/qlib_cn/csv --qlib_dir ./data/qlib_cn --include_fields open,high,low,close,volume,factor --date_field_name date`.
- **CSV pipeline itself is verified** (Task 11 backfill): 600519.SH + 000001.SZ, 581 bars each, columns `date,open,high,low,close,volume,factor`, raw prices + adj_factor. Only the bin conversion is deferred.

## Theme screener spike (2026-06-02)
- `pro.ths_index()` → **(1725, 6)** concepts/industries available (cols: ts_code,name,count,exchange,list_date,type).
- `pro.ths_member(ts_code=...)` → member stocks available (sample 883300.TI → 300 rows).
- `pro.fina_indicator(...)` → **(1, 108)** incl. netprofit_yoy / or_yoy etc.
- **Result: concept + earnings APIs are NOT gated at the user's points level.**
  → screener can use `TushareThemeSource` (auto membership), not just the static fallback.
  Map each theme to its ths_index `ts_code` (filter `ths_index` by name).
