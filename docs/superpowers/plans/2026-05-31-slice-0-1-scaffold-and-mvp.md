# Slice 0 + 1: Scaffold & Paper-Trading MVP — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up the monorepo (FastAPI + React), build the A-share historical data pipeline (tushare → qlib, correct adjustment handling), and a working daily mark-to-market paper-trading account with a minimal dashboard.

**Architecture:** Python FastAPI backend with layered modules (config, db, data-source interface + tushare adapter, qlib store, paper broker, REST API). React+Vite+TypeScript frontend talking REST. PostgreSQL for application state (accounts/positions/trades/equity). qlib for price/factor data stored as **raw OHLCV + adj_factor** (qfq/hfq derived on demand). Pure-logic units (adjustment math, paper broker) are TDD-first; integration points (tushare, qlib) are isolated behind interfaces and verified by a spike.

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy 2.x, pydantic-settings, pytest, tushare, pyqlib, pandas; React 18 + Vite + TypeScript + ECharts; PostgreSQL 15.

---

## Reference: Spec

Design spec: `docs/superpowers/specs/2026-05-31-ashare-trading-board-design.md`. Key constraints honored here:
- Store **non-adjusted OHLCV + adj_factor**; derive qfq/hfq. (§ data correctness)
- Equity **marked-to-market daily**; decision cadence weekly (decisions are slice 3 — not here).
- PostgreSQL for application data; qlib for price data.
- TradingAgents-CN kernel is a *later* dependency (slice 3); slice 0 only verifies it can be imported in isolation, does not wire it in.

---

## File Structure

### Backend (`backend/`)
```
backend/
  pyproject.toml                 # deps + tool config (ruff, pytest)
  .env.example                   # template (no secrets)
  app/
    __init__.py
    main.py                      # FastAPI app factory + router include
    config.py                    # Settings (pydantic-settings, reads .env)
    db/
      __init__.py
      database.py                # SQLAlchemy engine + SessionLocal + Base
      models.py                  # Account, Position, Trade, EquitySnapshot
    data/
      __init__.py
      source.py                  # MarketDataSource ABC + DailyBar dataclass
      tushare_source.py          # TushareSource(MarketDataSource)
      adjust.py                  # pure adjustment math (qfq/hfq from raw+factor)
      qlib_store.py              # dump bars to qlib bin format + load helpers
    trading/
      __init__.py
      schemas.py                 # pydantic request/response models
      broker.py                  # PaperBroker (pure logic over a session)
    api/
      __init__.py
      routes_account.py          # /api/account, /api/positions, /api/equity
      routes_trade.py            # POST /api/trade (manual buy/sell)
      routes_market.py           # /api/bars/{code}
  scripts/
    init_db.py                   # create tables
    backfill_history.py          # tushare → qlib N-year backfill
    daily_update.py              # incremental daily bar update + mark-to-market
  tests/
    conftest.py                  # in-memory sqlite session fixture
    test_config.py
    test_adjust.py               # ★ pure adjustment math
    test_broker.py               # ★ paper broker logic
    test_api_account.py
    test_api_trade.py
    test_tushare_source.py       # with mocked tushare client
```

### Frontend (`frontend/`)
```
frontend/
  package.json
  vite.config.ts
  tsconfig.json
  index.html
  src/
    main.tsx
    App.tsx
    api/client.ts                # fetch wrapper, typed
    pages/Dashboard.tsx          # account summary + positions table + equity chart
    components/PositionsTable.tsx
    components/EquityChart.tsx    # ECharts line
    components/TradeForm.tsx      # manual buy/sell
```

### Repo root
```
.env.example                     # points devs to backend/.env.example & frontend
README.md
docker-compose.yml               # postgres service for local dev
```

---

# PHASE A — Slice 0: Scaffold & De-risking

## Task 0: Environment spike (de-risk before any code)

**Why first:** Python is not installed; qlib/tushare/tradingagents installation is the single biggest risk. Verify the toolchain before writing features. This task has no unit tests — it is a verification gate with explicit expected outputs.

**Files:**
- Create: `docs/superpowers/plans/spike-notes.md` (record results)

- [ ] **Step 1: Install Python 3.11 + venv**

Run:
```bash
# Debian/Ubuntu base image
apt-get update && apt-get install -y python3.11 python3.11-venv python3-pip postgresql-client
python3.11 --version
```
Expected: `Python 3.11.x`. If `python3.11` unavailable, install via `deadsnakes` PPA or pyenv. Record exact method in spike-notes.md.

- [ ] **Step 2: Create venv and verify pip**

Run:
```bash
cd /root/.openclaw/workspace/ashare-trading-board
python3.11 -m venv backend/.venv
backend/.venv/bin/python -m pip install --upgrade pip
backend/.venv/bin/python -m pip --version
```
Expected: pip reports a version, venv path under `backend/.venv`.

- [ ] **Step 3: Spike qlib install (highest risk)**

Run:
```bash
backend/.venv/bin/pip install "pyqlib" numpy pandas
backend/.venv/bin/python -c "import qlib; print(qlib.__version__)"
```
Expected: prints a version (e.g. `0.9.x`). If it fails to build, record the error and fall back to: try `pip install pyqlib --no-build-isolation`, or pin `numpy<2`. Document the working recipe in spike-notes.md. **Do not proceed to Phase B data tasks until qlib imports.**

- [ ] **Step 4: Spike tushare with real token**

Run (token from user's .env, never commit):
```bash
backend/.venv/bin/pip install tushare
TUSHARE_TOKEN=*** backend/.venv/bin/python -c "
import os, tushare as ts
ts.set_token(os.environ['TUSHARE_TOKEN'])
pro = ts.pro_api()
df = pro.daily(ts_code='600519.SH', start_date='20260501', end_date='20260530')
print(df.shape); print(df.head())
df2 = ts.pro_bar(ts_code='600519.SH', adj=None, start_date='20260501', end_date='20260530')
print('pro_bar raw ok', df2.shape)
af = pro.adj_factor(ts_code='600519.SH', start_date='20260501', end_date='20260530')
print('adj_factor ok', af.shape)
"
```
Expected: three non-empty DataFrames. Confirms token works and `adj_factor` endpoint is accessible at the user's points level. Record column names in spike-notes.md (drives Task 5 schema).

- [ ] **Step 5: Spike tradingagents import in isolation (for slice 3 readiness)**

Run:
```bash
backend/.venv/bin/pip install "tradingagents" 2>&1 | tail -5 || echo "PyPI install failed — will vendor from git in slice 3"
backend/.venv/bin/python -c "import tradingagents; print('import ok')" 2>&1 | tail -3 || true
```
Expected: either import ok, or a recorded note that slice 3 must install from `hsliuping/TradingAgents-CN` git. **Not a blocker for slices 0/1** — just record the finding.

- [ ] **Step 6: Commit spike notes**

```bash
git add docs/superpowers/plans/spike-notes.md
git commit -m "chore: environment spike notes (python/qlib/tushare/tradingagents)"
```

---

## Task 1: Backend project skeleton + config

**Files:**
- Create: `backend/pyproject.toml`, `backend/.env.example`, `backend/app/__init__.py`, `backend/app/config.py`
- Test: `backend/tests/test_config.py`, `backend/tests/conftest.py`

- [ ] **Step 1: Write `backend/pyproject.toml`**

```toml
[project]
name = "ashare-backend"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
  "fastapi>=0.110",
  "uvicorn[standard]>=0.29",
  "sqlalchemy>=2.0",
  "psycopg2-binary>=2.9",
  "pydantic-settings>=2.2",
  "pandas>=2.0",
  "tushare>=1.4",
  "pyqlib",
]

[project.optional-dependencies]
dev = ["pytest>=8.0", "httpx>=0.27", "ruff>=0.4"]

[tool.pytest.ini_options]
pythonpath = ["."]
testpaths = ["tests"]

[tool.ruff]
line-length = 100
```

- [ ] **Step 2: Write `backend/.env.example`**

```
DATABASE_URL=postgresql+psycopg2://ashare:ashare@localhost:5432/ashare
TUSHARE_TOKEN=replace_me
DEEPSEEK_API_KEY=replace_me
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-v4-pro
QLIB_DATA_DIR=./data/qlib_cn
INITIAL_CASH=1000000
```

- [ ] **Step 3: Write the failing test `backend/tests/test_config.py`**

```python
from app.config import Settings

def test_settings_reads_env(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg2://u:p@h:5432/db")
    monkeypatch.setenv("TUSHARE_TOKEN", "tok")
    monkeypatch.setenv("INITIAL_CASH", "500000")
    s = Settings()
    assert s.database_url.startswith("postgresql")
    assert s.tushare_token == "tok"
    assert s.initial_cash == 500000
    assert s.deepseek_model == "deepseek-v4-pro"  # default
```

- [ ] **Step 4: Run test, expect failure**

Run: `backend/.venv/bin/python -m pytest tests/test_config.py -v` (from `backend/`)
Expected: FAIL — `ModuleNotFoundError: app.config`.

- [ ] **Step 5: Write `backend/app/config.py`**

```python
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg2://ashare:ashare@localhost:5432/ashare"
    tushare_token: str = ""
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-v4-pro"
    qlib_data_dir: str = "./data/qlib_cn"
    initial_cash: int = 1_000_000

def get_settings() -> Settings:
    return Settings()
```

Also create empty `backend/app/__init__.py`.

- [ ] **Step 6: Run test, expect pass**

Run: `backend/.venv/bin/python -m pytest tests/test_config.py -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/pyproject.toml backend/.env.example backend/app/__init__.py backend/app/config.py backend/tests/test_config.py
git commit -m "feat(backend): project skeleton and settings"
```

---

## Task 2: Database layer (engine, Base, session fixture)

**Files:**
- Create: `backend/app/db/__init__.py`, `backend/app/db/database.py`
- Test: `backend/tests/conftest.py`

- [ ] **Step 1: Write `backend/app/db/database.py`**

```python
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker
from app.config import get_settings

Base = declarative_base()

def make_engine(url: str | None = None):
    settings = get_settings()
    return create_engine(url or settings.database_url, future=True)

def make_session_factory(engine):
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)
```

Create empty `backend/app/db/__init__.py`.

- [ ] **Step 2: Write `backend/tests/conftest.py` (in-memory sqlite session)**

```python
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.db.database import Base
import app.db.models  # noqa: F401  ensure models are registered

@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    s = factory()
    try:
        yield s
    finally:
        s.close()
```

- [ ] **Step 3: Commit (no test yet — fixture validated by Task 3)**

```bash
git add backend/app/db/__init__.py backend/app/db/database.py backend/tests/conftest.py
git commit -m "feat(backend): db engine, Base, test session fixture"
```

---

## Task 3: ORM models (Account, Position, Trade, EquitySnapshot)

**Files:**
- Create: `backend/app/db/models.py`
- Test: `backend/tests/test_models.py`

- [ ] **Step 1: Write failing test `backend/tests/test_models.py`**

```python
from datetime import date
from app.db.models import Account, Position, Trade, EquitySnapshot

def test_account_relationships(session):
    acc = Account(name="main", cash=1000000.0)
    session.add(acc); session.commit()
    pos = Position(account_id=acc.id, code="600519.SH", shares=100, cost=1500.0)
    tr = Trade(account_id=acc.id, code="600519.SH", side="BUY", price=1500.0,
               shares=100, traded_at=date(2026, 5, 29))
    eq = EquitySnapshot(account_id=acc.id, as_of=date(2026, 5, 29),
                        cash=850000.0, market_value=150000.0, total=1000000.0)
    session.add_all([pos, tr, eq]); session.commit()
    assert acc.id is not None
    assert session.query(Position).filter_by(account_id=acc.id).count() == 1
    assert session.query(Trade).one().side == "BUY"
    assert session.query(EquitySnapshot).one().total == 1000000.0
```

- [ ] **Step 2: Run test, expect failure**

Run: `backend/.venv/bin/python -m pytest tests/test_models.py -v`
Expected: FAIL — `ModuleNotFoundError: app.db.models`.

- [ ] **Step 3: Write `backend/app/db/models.py`**

```python
from datetime import date
from sqlalchemy import String, Float, Integer, Date, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.database import Base

class Account(Base):
    __tablename__ = "accounts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True)
    cash: Mapped[float] = mapped_column(Float, default=0.0)
    positions: Mapped[list["Position"]] = relationship(back_populates="account")

class Position(Base):
    __tablename__ = "positions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"))
    code: Mapped[str] = mapped_column(String(16))
    shares: Mapped[int] = mapped_column(Integer, default=0)
    cost: Mapped[float] = mapped_column(Float, default=0.0)  # avg cost price
    account: Mapped["Account"] = relationship(back_populates="positions")

class Trade(Base):
    __tablename__ = "trades"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"))
    code: Mapped[str] = mapped_column(String(16))
    side: Mapped[str] = mapped_column(String(4))  # BUY / SELL
    price: Mapped[float] = mapped_column(Float)
    shares: Mapped[int] = mapped_column(Integer)
    traded_at: Mapped[date] = mapped_column(Date)

class EquitySnapshot(Base):
    __tablename__ = "equity_curve"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"))
    as_of: Mapped[date] = mapped_column(Date)
    cash: Mapped[float] = mapped_column(Float)
    market_value: Mapped[float] = mapped_column(Float)
    total: Mapped[float] = mapped_column(Float)
```

- [ ] **Step 4: Run test, expect pass**

Run: `backend/.venv/bin/python -m pytest tests/test_models.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/db/models.py backend/tests/test_models.py
git commit -m "feat(backend): ORM models for account/position/trade/equity"
```

---

## Task 4: FastAPI app factory + health route

**Files:**
- Create: `backend/app/main.py`, `backend/app/api/__init__.py`
- Test: `backend/tests/test_health.py`

- [ ] **Step 1: Write failing test `backend/tests/test_health.py`**

```python
from fastapi.testclient import TestClient
from app.main import create_app

def test_health():
    client = TestClient(create_app())
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}
```

- [ ] **Step 2: Run test, expect failure**

Run: `backend/.venv/bin/python -m pytest tests/test_health.py -v`
Expected: FAIL — cannot import `create_app`.

- [ ] **Step 3: Write `backend/app/main.py`**

```python
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

def create_app() -> FastAPI:
    app = FastAPI(title="A-Share Trading Board")
    app.add_middleware(
        CORSMiddleware, allow_origins=["http://localhost:5173"],
        allow_methods=["*"], allow_headers=["*"],
    )

    @app.get("/api/health")
    def health():
        return {"status": "ok"}

    return app

app = create_app()
```

Create empty `backend/app/api/__init__.py`.

- [ ] **Step 4: Run test, expect pass**

Run: `backend/.venv/bin/python -m pytest tests/test_health.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/main.py backend/app/api/__init__.py backend/tests/test_health.py
git commit -m "feat(backend): FastAPI app factory and health endpoint"
```

---

## Task 5: Frontend scaffold (Vite + React + TS)

**Files:**
- Create: `frontend/package.json`, `frontend/vite.config.ts`, `frontend/tsconfig.json`, `frontend/index.html`, `frontend/src/main.tsx`, `frontend/src/App.tsx`, `frontend/src/api/client.ts`

- [ ] **Step 1: Scaffold via Vite**

Run:
```bash
cd /root/.openclaw/workspace/ashare-trading-board
npm create vite@latest frontend -- --template react-ts
cd frontend && npm install && npm install echarts
```
Expected: `frontend/` created, `npm install` completes.

- [ ] **Step 2: Write `frontend/src/api/client.ts`**

```typescript
const BASE = import.meta.env.VITE_API_BASE ?? "http://localhost:8000";

export async function apiGet<T>(path: string): Promise<T> {
  const r = await fetch(`${BASE}${path}`);
  if (!r.ok) throw new Error(`GET ${path} failed: ${r.status}`);
  return r.json() as Promise<T>;
}

export async function apiPost<T>(path: string, body: unknown): Promise<T> {
  const r = await fetch(`${BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error(`POST ${path} failed: ${r.status}`);
  return r.json() as Promise<T>;
}
```

- [ ] **Step 3: Replace `frontend/src/App.tsx` with a health check**

```tsx
import { useEffect, useState } from "react";
import { apiGet } from "./api/client";

export default function App() {
  const [status, setStatus] = useState("checking...");
  useEffect(() => {
    apiGet<{ status: string }>("/api/health")
      .then((d) => setStatus(d.status))
      .catch((e) => setStatus("error: " + e.message));
  }, []);
  return <div style={{ padding: 24 }}><h1>A-Share Board</h1><p>backend: {status}</p></div>;
}
```

- [ ] **Step 4: Verify build**

Run: `cd frontend && npm run build`
Expected: build succeeds, `dist/` produced.

- [ ] **Step 5: Commit**

```bash
git add frontend/ -- ':!frontend/node_modules'
git commit -m "feat(frontend): vite react-ts scaffold with api client and health check"
```

---

## Task 6: Local Postgres via docker-compose + init script

**Files:**
- Create: `docker-compose.yml`, `backend/scripts/init_db.py`

> Note: host has no docker. If docker is unavailable at execution time, fall back to a native `postgresql` install or a managed PG URL in `.env`. The compose file is the documented default.

- [ ] **Step 1: Write `docker-compose.yml`**

```yaml
services:
  db:
    image: postgres:15
    environment:
      POSTGRES_USER: ashare
      POSTGRES_PASSWORD: ashare
      POSTGRES_DB: ashare
    ports: ["5432:5432"]
    volumes: ["pgdata:/var/lib/postgresql/data"]
volumes:
  pgdata:
```

- [ ] **Step 2: Write `backend/scripts/init_db.py`**

```python
from app.db.database import make_engine, Base
import app.db.models  # noqa: F401

def main():
    engine = make_engine()
    Base.metadata.create_all(engine)
    print("tables created")

if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Bring up DB and create tables**

Run:
```bash
docker compose up -d db   # or ensure native PG is running
cd backend && .venv/bin/python scripts/init_db.py
```
Expected: `tables created`. Verify: `psql postgresql://ashare:ashare@localhost:5432/ashare -c '\dt'` lists 4 tables.

- [ ] **Step 4: Commit**

```bash
git add docker-compose.yml backend/scripts/init_db.py
git commit -m "feat: local postgres compose and db init script"
```

---

# PHASE B — Slice 1: Historical Data + Paper Trading MVP

## Task 7: MarketDataSource interface + DailyBar

**Files:**
- Create: `backend/app/data/__init__.py`, `backend/app/data/source.py`
- Test: `backend/tests/test_source_contract.py`

- [ ] **Step 1: Write failing test `backend/tests/test_source_contract.py`**

```python
from datetime import date
from app.data.source import DailyBar, MarketDataSource

class FakeSource(MarketDataSource):
    def get_daily_bars(self, code, start, end):
        return [DailyBar(code=code, trade_date=date(2026,5,29),
                         open=10, high=11, low=9, close=10.5,
                         volume=1000, adj_factor=1.0)]

def test_dailybar_fields_and_interface():
    src = FakeSource()
    bars = src.get_daily_bars("600519.SH", date(2026,5,1), date(2026,5,30))
    assert len(bars) == 1
    b = bars[0]
    assert b.code == "600519.SH"
    assert b.close == 10.5
    assert b.adj_factor == 1.0
```

- [ ] **Step 2: Run test, expect failure**

Run: `backend/.venv/bin/python -m pytest tests/test_source_contract.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Write `backend/app/data/source.py`**

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date

@dataclass(frozen=True)
class DailyBar:
    code: str
    trade_date: date
    open: float
    high: float
    low: float
    close: float
    volume: float
    adj_factor: float  # raw (non-adjusted) prices + factor; qfq/hfq derived later

class MarketDataSource(ABC):
    @abstractmethod
    def get_daily_bars(self, code: str, start: date, end: date) -> list[DailyBar]:
        ...
```

Create empty `backend/app/data/__init__.py`.

- [ ] **Step 4: Run test, expect pass**

Run: `backend/.venv/bin/python -m pytest tests/test_source_contract.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/data/__init__.py backend/app/data/source.py backend/tests/test_source_contract.py
git commit -m "feat(data): MarketDataSource interface and DailyBar"
```

---

## Task 8: Adjustment math (qfq/hfq from raw + adj_factor) — ★ correctness-critical

**Files:**
- Create: `backend/app/data/adjust.py`
- Test: `backend/tests/test_adjust.py`

Rule (tushare convention): `hfq_price = raw_price * adj_factor`. `qfq_price = raw_price * adj_factor / latest_adj_factor` over the requested window. Volume is never adjusted.

- [ ] **Step 1: Write failing test `backend/tests/test_adjust.py`**

```python
from datetime import date
from app.data.source import DailyBar
from app.data.adjust import to_hfq, to_qfq

def _bar(d, close, af):
    return DailyBar("X", d, close, close, close, close, 1000, af)

def test_hfq_multiplies_by_factor():
    bars = [_bar(date(2026,1,2), 10.0, 1.0), _bar(date(2026,1,3), 11.0, 2.0)]
    out = to_hfq(bars)
    assert out[0].close == 10.0
    assert out[1].close == 22.0           # 11 * 2.0
    assert out[1].volume == 1000          # volume untouched

def test_qfq_normalizes_to_latest_factor():
    bars = [_bar(date(2026,1,2), 10.0, 1.0), _bar(date(2026,1,3), 11.0, 2.0)]
    out = to_qfq(bars)
    # latest factor = 2.0 -> qfq = raw * af / 2
    assert out[0].close == 5.0            # 10 * 1 / 2
    assert out[1].close == 11.0           # 11 * 2 / 2
    assert out[1].open == 11.0

def test_empty_returns_empty():
    assert to_hfq([]) == []
    assert to_qfq([]) == []
```

- [ ] **Step 2: Run test, expect failure**

Run: `backend/.venv/bin/python -m pytest tests/test_adjust.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Write `backend/app/data/adjust.py`**

```python
from dataclasses import replace
from app.data.source import DailyBar

def _scale(bar: DailyBar, k: float) -> DailyBar:
    return replace(bar, open=bar.open*k, high=bar.high*k,
                   low=bar.low*k, close=bar.close*k)  # volume untouched

def to_hfq(bars: list[DailyBar]) -> list[DailyBar]:
    return [_scale(b, b.adj_factor) for b in bars]

def to_qfq(bars: list[DailyBar]) -> list[DailyBar]:
    if not bars:
        return []
    latest = bars[-1].adj_factor
    return [_scale(b, b.adj_factor / latest) for b in bars]
```

- [ ] **Step 4: Run test, expect pass**

Run: `backend/.venv/bin/python -m pytest tests/test_adjust.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/app/data/adjust.py backend/tests/test_adjust.py
git commit -m "feat(data): qfq/hfq adjustment math from raw OHLCV + adj_factor"
```

---

## Task 9: Tushare adapter (mocked in tests)

**Files:**
- Create: `backend/app/data/tushare_source.py`
- Test: `backend/tests/test_tushare_source.py`

- [ ] **Step 1: Write failing test `backend/tests/test_tushare_source.py`**

```python
from datetime import date
import pandas as pd
from app.data.tushare_source import TushareSource

class FakePro:
    def daily(self, ts_code, start_date, end_date):
        return pd.DataFrame({
            "ts_code": [ts_code, ts_code],
            "trade_date": ["20260103", "20260102"],   # tushare returns desc
            "open": [11.0, 10.0], "high": [11.5, 10.5],
            "low": [10.8, 9.8], "close": [11.0, 10.0], "vol": [2000.0, 1000.0],
        })
    def adj_factor(self, ts_code, start_date, end_date):
        return pd.DataFrame({
            "trade_date": ["20260103", "20260102"],
            "adj_factor": [2.0, 1.0],
        })

def test_returns_sorted_bars_with_factor():
    src = TushareSource(pro=FakePro())
    bars = src.get_daily_bars("600519.SH", date(2026,1,1), date(2026,1,5))
    assert [b.trade_date for b in bars] == [date(2026,1,2), date(2026,1,3)]  # ascending
    assert bars[0].close == 10.0 and bars[0].adj_factor == 1.0
    assert bars[1].close == 11.0 and bars[1].adj_factor == 2.0
    assert bars[1].volume == 2000.0
```

- [ ] **Step 2: Run test, expect failure**

Run: `backend/.venv/bin/python -m pytest tests/test_tushare_source.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Write `backend/app/data/tushare_source.py`**

```python
from datetime import date
import pandas as pd
from app.data.source import DailyBar, MarketDataSource

def _fmt(d: date) -> str:
    return d.strftime("%Y%m%d")

def _parse(s: str) -> date:
    return date(int(s[:4]), int(s[4:6]), int(s[6:8]))

class TushareSource(MarketDataSource):
    def __init__(self, pro=None, token: str | None = None):
        if pro is not None:
            self.pro = pro
        else:
            import tushare as ts
            ts.set_token(token or "")
            self.pro = ts.pro_api()

    def get_daily_bars(self, code: str, start: date, end: date) -> list[DailyBar]:
        daily = self.pro.daily(ts_code=code, start_date=_fmt(start), end_date=_fmt(end))
        adj = self.pro.adj_factor(ts_code=code, start_date=_fmt(start), end_date=_fmt(end))
        merged = daily.merge(adj[["trade_date", "adj_factor"]], on="trade_date", how="left")
        merged = merged.sort_values("trade_date")  # ascending
        bars: list[DailyBar] = []
        for _, r in merged.iterrows():
            bars.append(DailyBar(
                code=code, trade_date=_parse(str(r["trade_date"])),
                open=float(r["open"]), high=float(r["high"]), low=float(r["low"]),
                close=float(r["close"]), volume=float(r["vol"]),
                adj_factor=float(r["adj_factor"]) if pd.notna(r["adj_factor"]) else 1.0,
            ))
        return bars
```

- [ ] **Step 4: Run test, expect pass**

Run: `backend/.venv/bin/python -m pytest tests/test_tushare_source.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/data/tushare_source.py backend/tests/test_tushare_source.py
git commit -m "feat(data): tushare adapter merging daily + adj_factor"
```

---

## Task 10: qlib store (dump bars to qlib bin format)

**Files:**
- Create: `backend/app/data/qlib_store.py`
- Test: `backend/tests/test_qlib_store.py`

> qlib ingests CSV-per-instrument then `dump_bin`. We write raw OHLCV + adj_factor as columns so qlib holds non-adjusted data; adjustment happens in our layer.

- [ ] **Step 1: Write failing test `backend/tests/test_qlib_store.py`**

```python
from datetime import date
import pandas as pd
from app.data.source import DailyBar
from app.data.qlib_store import bars_to_dataframe

def test_bars_to_dataframe_has_expected_columns():
    bars = [DailyBar("600519.SH", date(2026,1,2), 10,11,9,10.5,1000,1.0)]
    df = bars_to_dataframe(bars)
    assert list(df.columns) == ["date","open","high","low","close","volume","factor"]
    assert df.iloc[0]["close"] == 10.5
    assert df.iloc[0]["factor"] == 1.0
    assert str(df.iloc[0]["date"]) == "2026-01-02"
```

- [ ] **Step 2: Run test, expect failure**

Run: `backend/.venv/bin/python -m pytest tests/test_qlib_store.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Write `backend/app/data/qlib_store.py`**

```python
from pathlib import Path
import pandas as pd
from app.data.source import DailyBar

COLUMNS = ["date", "open", "high", "low", "close", "volume", "factor"]

def bars_to_dataframe(bars: list[DailyBar]) -> pd.DataFrame:
    rows = [{
        "date": b.trade_date, "open": b.open, "high": b.high, "low": b.low,
        "close": b.close, "volume": b.volume, "factor": b.adj_factor,
    } for b in bars]
    return pd.DataFrame(rows, columns=COLUMNS)

def write_instrument_csv(bars: list[DailyBar], out_dir: str) -> Path:
    """Write one CSV per instrument for later `qlib dump_bin`."""
    assert bars, "no bars to write"
    df = bars_to_dataframe(bars)
    out = Path(out_dir); out.mkdir(parents=True, exist_ok=True)
    path = out / f"{bars[0].code}.csv"
    df.to_csv(path, index=False)
    return path
```

- [ ] **Step 4: Run test, expect pass**

Run: `backend/.venv/bin/python -m pytest tests/test_qlib_store.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/data/qlib_store.py backend/tests/test_qlib_store.py
git commit -m "feat(data): qlib store helpers (bars -> dataframe/csv)"
```

---

## Task 11: Backfill + daily-update scripts (integration, manual run)

**Files:**
- Create: `backend/scripts/backfill_history.py`, `backend/scripts/daily_update.py`

> These are thin orchestration scripts over already-tested units; verified by manual run against the real tushare token, not unit tests.

- [ ] **Step 1: Write `backend/scripts/backfill_history.py`**

```python
import argparse
from datetime import date
from app.config import get_settings
from app.data.tushare_source import TushareSource
from app.data.qlib_store import write_instrument_csv

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--codes", nargs="+", required=True)
    p.add_argument("--start", default="20180101")
    p.add_argument("--end", default=date.today().strftime("%Y%m%d"))
    args = p.parse_args()
    s = get_settings()
    src = TushareSource(token=s.tushare_token)
    def _d(x): return date(int(x[:4]), int(x[4:6]), int(x[6:8]))
    for code in args.codes:
        bars = src.get_daily_bars(code, _d(args.start), _d(args.end))
        path = write_instrument_csv(bars, f"{s.qlib_data_dir}/csv")
        print(f"{code}: {len(bars)} bars -> {path}")

if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Manual verify backfill**

Run (from `backend/`, .env populated):
```bash
.venv/bin/python scripts/backfill_history.py --codes 600519.SH 000001.SZ --start 20240101
```
Expected: prints bar counts and CSV paths; CSV files exist under `data/qlib_cn/csv/`.

- [ ] **Step 3: Convert to qlib bin (documented command)**

Run:
```bash
.venv/bin/python -m qlib.scripts.dump_bin dump_all \
  --csv_path ./data/qlib_cn/csv --qlib_dir ./data/qlib_cn \
  --include_fields open,high,low,close,volume,factor
```
Expected: qlib bin files under `data/qlib_cn/features`. Record exact invocation in spike-notes if flags differ by qlib version.

- [ ] **Step 4: Write `backend/scripts/daily_update.py`**

```python
"""Incremental: fetch latest trading day bars, append CSVs, then mark-to-market.
Mark-to-market is invoked from the broker (Task 13) once accounts exist."""
import argparse
from datetime import date, timedelta
from app.config import get_settings
from app.data.tushare_source import TushareSource
from app.data.qlib_store import write_instrument_csv

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--codes", nargs="+", required=True)
    p.add_argument("--days", type=int, default=5)
    args = p.parse_args()
    s = get_settings()
    src = TushareSource(token=s.tushare_token)
    end = date.today(); start = end - timedelta(days=args.days)
    for code in args.codes:
        bars = src.get_daily_bars(code, start, end)
        if bars:
            write_instrument_csv(bars, f"{s.qlib_data_dir}/csv_incr")
            print(f"{code}: {len(bars)} recent bars")

if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Commit**

```bash
git add backend/scripts/backfill_history.py backend/scripts/daily_update.py
git commit -m "feat(scripts): tushare backfill and daily incremental update"
```

---

## Task 12: Latest-price helper (read close for mark-to-market)

**Files:**
- Create: `backend/app/data/prices.py`
- Test: `backend/tests/test_prices.py`

> The broker needs "latest close per code". For the MVP we read from a simple dict-like provider so the broker stays testable without qlib. A qlib-backed implementation can replace it later.

- [ ] **Step 1: Write failing test `backend/tests/test_prices.py`**

```python
from app.data.prices import DictPriceProvider

def test_dict_price_provider():
    p = DictPriceProvider({"600519.SH": 1500.0, "000001.SZ": 12.3})
    assert p.latest_close("600519.SH") == 1500.0
    assert p.latest_close("000001.SZ") == 12.3

def test_missing_code_raises():
    p = DictPriceProvider({})
    try:
        p.latest_close("X")
        assert False, "expected KeyError"
    except KeyError:
        pass
```

- [ ] **Step 2: Run test, expect failure**

Run: `backend/.venv/bin/python -m pytest tests/test_prices.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Write `backend/app/data/prices.py`**

```python
from abc import ABC, abstractmethod

class PriceProvider(ABC):
    @abstractmethod
    def latest_close(self, code: str) -> float: ...

class DictPriceProvider(PriceProvider):
    def __init__(self, prices: dict[str, float]):
        self._prices = prices
    def latest_close(self, code: str) -> float:
        return self._prices[code]
```

- [ ] **Step 4: Run test, expect pass**

Run: `backend/.venv/bin/python -m pytest tests/test_prices.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/data/prices.py backend/tests/test_prices.py
git commit -m "feat(data): PriceProvider interface + dict impl for mark-to-market"
```

---

## Task 13: PaperBroker — buy/sell/mark-to-market — ★ core of slice 1

**Files:**
- Create: `backend/app/trading/__init__.py`, `backend/app/trading/broker.py`
- Test: `backend/tests/test_broker.py`

Rules: BUY decreases cash by `price*shares` (reject if insufficient cash), creates/updates position with weighted-average cost. SELL increases cash, reduces shares (reject if insufficient shares); removes position at zero. `mark_to_market` writes an EquitySnapshot: cash + Σ shares*latest_close.

- [ ] **Step 1: Write failing test `backend/tests/test_broker.py`**

```python
from datetime import date
import pytest
from app.db.models import Account
from app.data.prices import DictPriceProvider
from app.trading.broker import PaperBroker, InsufficientFunds, InsufficientShares

@pytest.fixture
def account(session):
    acc = Account(name="main", cash=100000.0)
    session.add(acc); session.commit()
    return acc

def test_buy_decrements_cash_and_creates_position(session, account):
    b = PaperBroker(session)
    b.buy(account.id, "600519.SH", price=1000.0, shares=50, on=date(2026,5,29))
    session.refresh(account)
    assert account.cash == 50000.0
    pos = b.get_position(account.id, "600519.SH")
    assert pos.shares == 50 and pos.cost == 1000.0

def test_buy_averages_cost(session, account):
    b = PaperBroker(session)
    b.buy(account.id, "X", price=10.0, shares=100, on=date(2026,5,29))
    b.buy(account.id, "X", price=20.0, shares=100, on=date(2026,5,30))
    pos = b.get_position(account.id, "X")
    assert pos.shares == 200 and pos.cost == 15.0

def test_buy_insufficient_cash_rejected(session, account):
    b = PaperBroker(session)
    with pytest.raises(InsufficientFunds):
        b.buy(account.id, "X", price=1.0, shares=10**9, on=date(2026,5,29))

def test_sell_reduces_shares_and_adds_cash(session, account):
    b = PaperBroker(session)
    b.buy(account.id, "X", price=10.0, shares=100, on=date(2026,5,29))
    b.sell(account.id, "X", price=12.0, shares=60, on=date(2026,5,30))
    session.refresh(account)
    assert account.cash == 100000.0 - 1000.0 + 720.0
    assert b.get_position(account.id, "X").shares == 40

def test_sell_too_many_rejected(session, account):
    b = PaperBroker(session)
    b.buy(account.id, "X", price=10.0, shares=10, on=date(2026,5,29))
    with pytest.raises(InsufficientShares):
        b.sell(account.id, "X", price=10.0, shares=11, on=date(2026,5,30))

def test_mark_to_market_writes_snapshot(session, account):
    b = PaperBroker(session)
    b.buy(account.id, "X", price=10.0, shares=100, on=date(2026,5,29))   # cash 99000
    prices = DictPriceProvider({"X": 12.0})
    snap = b.mark_to_market(account.id, prices, on=date(2026,5,29))
    assert snap.cash == 99000.0
    assert snap.market_value == 1200.0
    assert snap.total == 100200.0
```

- [ ] **Step 2: Run test, expect failure**

Run: `backend/.venv/bin/python -m pytest tests/test_broker.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Write `backend/app/trading/broker.py`**

```python
from datetime import date
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.db.models import Account, Position, Trade, EquitySnapshot
from app.data.prices import PriceProvider

class InsufficientFunds(Exception): ...
class InsufficientShares(Exception): ...

class PaperBroker:
    def __init__(self, session: Session):
        self.s = session

    def get_position(self, account_id: int, code: str) -> Position | None:
        return self.s.scalar(
            select(Position).where(Position.account_id == account_id, Position.code == code)
        )

    def _account(self, account_id: int) -> Account:
        return self.s.get(Account, account_id)

    def buy(self, account_id, code, price, shares, on: date):
        acc = self._account(account_id)
        cost = price * shares
        if cost > acc.cash:
            raise InsufficientFunds(f"need {cost}, have {acc.cash}")
        acc.cash -= cost
        pos = self.get_position(account_id, code)
        if pos is None:
            pos = Position(account_id=account_id, code=code, shares=0, cost=0.0)
            self.s.add(pos)
        new_shares = pos.shares + shares
        pos.cost = (pos.cost * pos.shares + price * shares) / new_shares
        pos.shares = new_shares
        self.s.add(Trade(account_id=account_id, code=code, side="BUY",
                         price=price, shares=shares, traded_at=on))
        self.s.commit()

    def sell(self, account_id, code, price, shares, on: date):
        pos = self.get_position(account_id, code)
        if pos is None or shares > pos.shares:
            raise InsufficientShares(f"sell {shares}, have {pos.shares if pos else 0}")
        acc = self._account(account_id)
        acc.cash += price * shares
        pos.shares -= shares
        if pos.shares == 0:
            self.s.delete(pos)
        self.s.add(Trade(account_id=account_id, code=code, side="SELL",
                         price=price, shares=shares, traded_at=on))
        self.s.commit()

    def mark_to_market(self, account_id, prices: PriceProvider, on: date) -> EquitySnapshot:
        acc = self._account(account_id)
        positions = self.s.scalars(
            select(Position).where(Position.account_id == account_id)
        ).all()
        mv = sum(p.shares * prices.latest_close(p.code) for p in positions)
        snap = EquitySnapshot(account_id=account_id, as_of=on, cash=acc.cash,
                              market_value=mv, total=acc.cash + mv)
        self.s.add(snap); self.s.commit()
        return snap
```

Create empty `backend/app/trading/__init__.py`.

- [ ] **Step 4: Run test, expect pass**

Run: `backend/.venv/bin/python -m pytest tests/test_broker.py -v`
Expected: PASS (7 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/app/trading/__init__.py backend/app/trading/broker.py backend/tests/test_broker.py
git commit -m "feat(trading): PaperBroker buy/sell/mark-to-market with weighted-avg cost"
```

---

## Task 14: Pydantic schemas + account/trade API

**Files:**
- Create: `backend/app/trading/schemas.py`, `backend/app/api/routes_account.py`, `backend/app/api/routes_trade.py`
- Modify: `backend/app/main.py` (include routers, add DB session dependency)
- Test: `backend/tests/test_api_trade.py`

- [ ] **Step 1: Write failing test `backend/tests/test_api_trade.py`**

```python
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.db.database import Base
import app.db.models  # noqa
from app.db.models import Account
from app.main import create_app
from app.api.deps import get_session

def _client_with_db():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    s = factory()
    s.add(Account(name="main", cash=100000.0)); s.commit()
    app = create_app()
    app.dependency_overrides[get_session] = lambda: s
    return TestClient(app), s

def test_buy_then_account_reflects_position():
    client, _ = _client_with_db()
    r = client.post("/api/trade", json={"account_id":1,"code":"X","side":"BUY",
                                        "price":10.0,"shares":100,"on":"2026-05-29"})
    assert r.status_code == 200
    acc = client.get("/api/account/1").json()
    assert acc["cash"] == 99000.0
    assert acc["positions"][0]["code"] == "X"
    assert acc["positions"][0]["shares"] == 100
```

- [ ] **Step 2: Run test, expect failure**

Run: `backend/.venv/bin/python -m pytest tests/test_api_trade.py -v`
Expected: FAIL — `app.api.deps` / routes missing.

- [ ] **Step 3: Write `backend/app/api/deps.py`**

```python
from app.db.database import make_engine, make_session_factory

_engine = None
_factory = None

def get_session():
    global _engine, _factory
    if _factory is None:
        _engine = make_engine()
        _factory = make_session_factory(_engine)
    s = _factory()
    try:
        yield s
    finally:
        s.close()
```

- [ ] **Step 4: Write `backend/app/trading/schemas.py`**

```python
from datetime import date
from pydantic import BaseModel

class TradeRequest(BaseModel):
    account_id: int
    code: str
    side: str  # BUY / SELL
    price: float
    shares: int
    on: date

class PositionOut(BaseModel):
    code: str
    shares: int
    cost: float

class AccountOut(BaseModel):
    id: int
    name: str
    cash: float
    positions: list[PositionOut]

class EquityPoint(BaseModel):
    as_of: date
    cash: float
    market_value: float
    total: float
```

- [ ] **Step 5: Write `backend/app/api/routes_trade.py`**

```python
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.api.deps import get_session
from app.trading.broker import PaperBroker, InsufficientFunds, InsufficientShares
from app.trading.schemas import TradeRequest

router = APIRouter(prefix="/api", tags=["trade"])

@router.post("/trade")
def trade(req: TradeRequest, s: Session = Depends(get_session)):
    broker = PaperBroker(s)
    try:
        if req.side == "BUY":
            broker.buy(req.account_id, req.code, req.price, req.shares, req.on)
        elif req.side == "SELL":
            broker.sell(req.account_id, req.code, req.price, req.shares, req.on)
        else:
            raise HTTPException(400, "side must be BUY or SELL")
    except (InsufficientFunds, InsufficientShares) as e:
        raise HTTPException(400, str(e))
    return {"status": "ok"}
```

- [ ] **Step 6: Write `backend/app/api/routes_account.py`**

```python
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.api.deps import get_session
from app.db.models import Account, Position, EquitySnapshot
from app.trading.schemas import AccountOut, PositionOut, EquityPoint

router = APIRouter(prefix="/api", tags=["account"])

@router.get("/account/{account_id}", response_model=AccountOut)
def get_account(account_id: int, s: Session = Depends(get_session)):
    acc = s.get(Account, account_id)
    if acc is None:
        raise HTTPException(404, "account not found")
    positions = s.scalars(select(Position).where(Position.account_id == account_id)).all()
    return AccountOut(id=acc.id, name=acc.name, cash=acc.cash,
                      positions=[PositionOut(code=p.code, shares=p.shares, cost=p.cost)
                                 for p in positions])

@router.get("/equity/{account_id}", response_model=list[EquityPoint])
def get_equity(account_id: int, s: Session = Depends(get_session)):
    rows = s.scalars(
        select(EquitySnapshot).where(EquitySnapshot.account_id == account_id)
        .order_by(EquitySnapshot.as_of)
    ).all()
    return [EquityPoint(as_of=r.as_of, cash=r.cash,
                        market_value=r.market_value, total=r.total) for r in rows]
```

- [ ] **Step 7: Modify `backend/app/main.py` to include routers**

Replace the body of `create_app` to add, after CORS middleware:

```python
    from app.api import routes_account, routes_trade
    app.include_router(routes_account.router)
    app.include_router(routes_trade.router)
```

(keep the existing `/api/health` route and `return app`.)

- [ ] **Step 8: Run test, expect pass**

Run: `backend/.venv/bin/python -m pytest tests/test_api_trade.py -v`
Expected: PASS.

- [ ] **Step 9: Run full suite**

Run: `backend/.venv/bin/python -m pytest -v`
Expected: all tests PASS.

- [ ] **Step 10: Commit**

```bash
git add backend/app/api backend/app/trading/schemas.py backend/app/main.py backend/tests/test_api_trade.py
git commit -m "feat(api): account + trade endpoints over PaperBroker"
```

---

## Task 15: Seed script + market bars endpoint

**Files:**
- Create: `backend/scripts/seed_account.py`, `backend/app/api/routes_market.py`
- Modify: `backend/app/main.py` (include market router)
- Test: `backend/tests/test_api_market.py`

- [ ] **Step 1: Write `backend/scripts/seed_account.py`**

```python
from app.api.deps import get_session
from app.db.models import Account
from app.config import get_settings

def main():
    s = next(get_session())
    if s.query(Account).filter_by(name="main").first() is None:
        s.add(Account(name="main", cash=float(get_settings().initial_cash))); s.commit()
        print("seeded main account")
    else:
        print("main account already exists")

if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Write failing test `backend/tests/test_api_market.py`**

```python
from fastapi.testclient import TestClient
from app.main import create_app
from app.api.routes_market import get_price_provider
from app.data.prices import DictPriceProvider

def test_bars_latest_close():
    app = create_app()
    app.dependency_overrides[get_price_provider] = lambda: DictPriceProvider({"X": 9.9})
    client = TestClient(app)
    r = client.get("/api/price/X")
    assert r.status_code == 200
    assert r.json() == {"code": "X", "close": 9.9}
```

- [ ] **Step 3: Run test, expect failure**

Run: `backend/.venv/bin/python -m pytest tests/test_api_market.py -v`
Expected: FAIL — module missing.

- [ ] **Step 4: Write `backend/app/api/routes_market.py`**

```python
from fastapi import APIRouter, Depends, HTTPException
from app.data.prices import PriceProvider, DictPriceProvider

router = APIRouter(prefix="/api", tags=["market"])

def get_price_provider() -> PriceProvider:
    # MVP placeholder; replaced by a qlib-backed provider later.
    return DictPriceProvider({})

@router.get("/price/{code}")
def price(code: str, pp: PriceProvider = Depends(get_price_provider)):
    try:
        return {"code": code, "close": pp.latest_close(code)}
    except KeyError:
        raise HTTPException(404, f"no price for {code}")
```

- [ ] **Step 5: Add market router to `main.py`**

In `create_app`, extend the import/include block:
```python
    from app.api import routes_account, routes_trade, routes_market
    app.include_router(routes_account.router)
    app.include_router(routes_trade.router)
    app.include_router(routes_market.router)
```

- [ ] **Step 6: Run test, expect pass**

Run: `backend/.venv/bin/python -m pytest tests/test_api_market.py -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/scripts/seed_account.py backend/app/api/routes_market.py backend/app/main.py backend/tests/test_api_market.py
git commit -m "feat(api): price endpoint + account seed script"
```

---

## Task 16: Dashboard UI (account summary, positions, equity chart, trade form)

**Files:**
- Create: `frontend/src/pages/Dashboard.tsx`, `frontend/src/components/PositionsTable.tsx`, `frontend/src/components/EquityChart.tsx`, `frontend/src/components/TradeForm.tsx`
- Modify: `frontend/src/App.tsx`

- [ ] **Step 1: Write `frontend/src/components/PositionsTable.tsx`**

```tsx
type Position = { code: string; shares: number; cost: number };

export function PositionsTable({ positions }: { positions: Position[] }) {
  if (!positions.length) return <p>无持仓</p>;
  return (
    <table>
      <thead><tr><th>代码</th><th>股数</th><th>成本</th></tr></thead>
      <tbody>
        {positions.map((p) => (
          <tr key={p.code}><td>{p.code}</td><td>{p.shares}</td><td>{p.cost.toFixed(2)}</td></tr>
        ))}
      </tbody>
    </table>
  );
}
```

- [ ] **Step 2: Write `frontend/src/components/EquityChart.tsx`**

```tsx
import { useEffect, useRef } from "react";
import * as echarts from "echarts";

type Point = { as_of: string; total: number };

export function EquityChart({ points }: { points: Point[] }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!ref.current) return;
    const chart = echarts.init(ref.current);
    chart.setOption({
      xAxis: { type: "category", data: points.map((p) => p.as_of) },
      yAxis: { type: "value", scale: true },
      series: [{ type: "line", data: points.map((p) => p.total), smooth: true }],
      tooltip: { trigger: "axis" },
    });
    return () => chart.dispose();
  }, [points]);
  return <div ref={ref} style={{ width: "100%", height: 300 }} />;
}
```

- [ ] **Step 3: Write `frontend/src/components/TradeForm.tsx`**

```tsx
import { useState } from "react";
import { apiPost } from "../api/client";

export function TradeForm({ accountId, onDone }: { accountId: number; onDone: () => void }) {
  const [code, setCode] = useState("600519.SH");
  const [side, setSide] = useState("BUY");
  const [price, setPrice] = useState(1500);
  const [shares, setShares] = useState(100);
  const [msg, setMsg] = useState("");

  async function submit() {
    try {
      await apiPost("/api/trade", {
        account_id: accountId, code, side, price, shares,
        on: new Date().toISOString().slice(0, 10),
      });
      setMsg("成交"); onDone();
    } catch (e) { setMsg("失败: " + (e as Error).message); }
  }

  return (
    <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
      <input value={code} onChange={(e) => setCode(e.target.value)} />
      <select value={side} onChange={(e) => setSide(e.target.value)}>
        <option>BUY</option><option>SELL</option>
      </select>
      <input type="number" value={price} onChange={(e) => setPrice(+e.target.value)} />
      <input type="number" value={shares} onChange={(e) => setShares(+e.target.value)} />
      <button onClick={submit}>下单</button><span>{msg}</span>
    </div>
  );
}
```

- [ ] **Step 4: Write `frontend/src/pages/Dashboard.tsx`**

```tsx
import { useCallback, useEffect, useState } from "react";
import { apiGet } from "../api/client";
import { PositionsTable } from "../components/PositionsTable";
import { EquityChart } from "../components/EquityChart";
import { TradeForm } from "../components/TradeForm";

type Account = { id: number; name: string; cash: number;
  positions: { code: string; shares: number; cost: number }[] };
type Equity = { as_of: string; total: number }[];

const ACCOUNT_ID = 1;

export function Dashboard() {
  const [acc, setAcc] = useState<Account | null>(null);
  const [eq, setEq] = useState<Equity>([]);

  const load = useCallback(() => {
    apiGet<Account>(`/api/account/${ACCOUNT_ID}`).then(setAcc).catch(() => {});
    apiGet<Equity>(`/api/equity/${ACCOUNT_ID}`).then(setEq).catch(() => {});
  }, []);
  useEffect(load, [load]);

  if (!acc) return <p>加载中…</p>;
  return (
    <div style={{ padding: 24, display: "grid", gap: 16 }}>
      <h1>{acc.name} 模拟账户</h1>
      <p>现金: {acc.cash.toFixed(2)}</p>
      <TradeForm accountId={ACCOUNT_ID} onDone={load} />
      <h2>持仓</h2>
      <PositionsTable positions={acc.positions} />
      <h2>净值曲线</h2>
      <EquityChart points={eq} />
    </div>
  );
}
```

- [ ] **Step 5: Update `frontend/src/App.tsx`**

```tsx
import { Dashboard } from "./pages/Dashboard";
export default function App() { return <Dashboard />; }
```

- [ ] **Step 6: Build to verify types**

Run: `cd frontend && npm run build`
Expected: build succeeds.

- [ ] **Step 7: Commit**

```bash
git add frontend/src -- ':!frontend/node_modules'
git commit -m "feat(frontend): dashboard with positions, equity chart, trade form"
```

---

## Task 17: End-to-end manual verification + README

**Files:**
- Create: `README.md`

- [ ] **Step 1: Start backend**

Run:
```bash
cd backend && .venv/bin/python scripts/init_db.py && .venv/bin/python scripts/seed_account.py
.venv/bin/uvicorn app.main:app --reload --port 8000
```
Expected: server up; `curl localhost:8000/api/health` → `{"status":"ok"}`; `curl localhost:8000/api/account/1` → account with cash = INITIAL_CASH.

- [ ] **Step 2: Start frontend, place a trade**

Run: `cd frontend && npm run dev`
Open `http://localhost:5173`, submit a BUY via the form. Expected: cash decreases, position appears in table.

- [ ] **Step 3: Mark-to-market smoke (manual python)**

Run from `backend/`:
```bash
.venv/bin/python -c "
from app.api.deps import get_session
from app.trading.broker import PaperBroker
from app.data.prices import DictPriceProvider
from datetime import date
s=next(get_session()); b=PaperBroker(s)
print(b.mark_to_market(1, DictPriceProvider({'600519.SH':1600.0}), date.today()).total)
"
```
Expected: prints a total; refresh dashboard → equity chart shows a point.

- [ ] **Step 4: Write `README.md`** (run instructions: prerequisites, backend setup, frontend setup, env vars, how to backfill data, how to run tests). Include the exact commands from Tasks 0/1/6/11/17.

- [ ] **Step 5: Commit + push**

```bash
git add README.md
git commit -m "docs: README with setup, data backfill, and run instructions"
git push origin main
```

---

## Self-Review (completed by author)

**Spec coverage:**
- Monorepo FastAPI + React → Tasks 1,4,5 ✓
- Python env install → Task 0 ✓
- Historical data build (slice 1a) → Tasks 9,10,11 ✓
- Adjustment: raw OHLCV + adj_factor, derive qfq/hfq → Tasks 7,8,10 ✓
- PostgreSQL application data → Tasks 2,3,6 ✓
- Paper trading, daily mark-to-market → Tasks 12,13 ✓
- Minimal dashboard (positions, equity, manual order) → Task 16 ✓
- tradingagents import readiness (slice 3) → Task 0 Step 5 ✓ (verify only, not wired)
- GitHub sync → Task 17 push ✓
- Top-N / discovery / decision / scrapling → **out of scope** (slices 2–4), correctly deferred.

**Placeholder scan:** No TBD/TODO; every code step has full code; manual-run tasks (11,17) are explicitly integration tasks with expected outputs rather than unit tests.

**Type consistency:** `DailyBar` fields consistent across source/adjust/tushare/qlib_store. `PaperBroker` method names (`buy/sell/mark_to_market/get_position`) consistent across broker, API, tests. `PriceProvider.latest_close` consistent across prices/broker/market route. `get_session` dependency consistent across deps/routes/tests.

**Known execution risks (flagged, not blockers):**
- qlib install (Task 0 Step 3) and the `dump_bin` invocation (Task 11 Step 3) may need version-specific flags — recorded in spike-notes.
- Host has no docker → Postgres may need native install or a managed URL (Task 6 note).
- `pyqlib` may not support Python 3.13; plan pins 3.11 deliberately.
