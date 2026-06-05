# 分钟级 K 线图 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 点击界面任意股票弹出该股分钟级 K 线(KLineCharts,可切 1/5/15/30/60min);关注股(输入辩论∪跟踪∪决策∪持仓)由后端守护盘中持续采集进库,前端只读库。

**Architecture:** 新 SQL 表 `minute_quotes` + `MinuteStore`;`MinuteFetcher` 走 tushare `stk_mins`(全局 RateLimiter 1/min);`minute_universe` 算关注股;`minute_updater_daemon` 盘中 round-robin 增量采集;`GET /api/kline/{code}` 只读库;前端 klinecharts 图 + 全局 `StockChartProvider/Modal` + `StockLink` 接入各列表。设计见 `/root/.claude/plans/radiant-napping-alpaca.md`。

**Tech Stack:** FastAPI + SQLAlchemy + pytest;React + antd + klinecharts + vitest;tushare stk_mins。

---

## 通用约定
- 后端 `backend/`,`.venv/bin/python`/`.venv/bin/pytest`。前端 `frontend/`,`npx vitest run`、`VITE_API_BASE="" npm run build`。
- 分支 `feat/minute-kline`(基于 feat/decision-portfolio-enhance),commit 在此。每任务只 `git add` 本任务文件;并行时 git `index.lock` 则 `sleep 2` 重试一次。
- 模型类名(已确认,都有 `code` 列):`Position`/`Decision`/`TrackEntry`(表 tracklist)/`DecisionJob`。
- `models.py` 顶部当前导入 `from sqlalchemy import String, Float, Integer, Date, ForeignKey, Index` 与 `from datetime import date` —— 新表需补 `DateTime`(sqlalchemy)与 `datetime`(typing)。
- upsert 用 `session.merge(Model(**row))`(沿用 `app/data/quote_store.py:12`)。

## 文件结构
- 后端:`app/db/models.py`(+MinuteQuote)、`app/data/minute_store.py`、`app/data/minute_fetch.py`、`app/data/minute_universe.py`、`app/data/minute_updater.py`(可测核心 `update_codes`/`in_market_hours`)、`scripts/minute_updater_daemon.py`(薄 CLI)、`app/api/routes_kline.py`、`app/main.py`(注册)。
- 前端:`src/components/{KLineChart,StockChartProvider,StockChartModal,StockLink}.tsx`、`src/main.tsx`、6 个列表/页接 `StockLink`。

---

### Task 1: MinuteQuote 模型 + MinuteStore

**Files:** Modify `app/db/models.py`;Create `app/data/minute_store.py`;Test `tests/test_minute_store.py`

- [ ] **Step 1: 写测试** `tests/test_minute_store.py`:

```python
from datetime import datetime
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.db.database import Base
import app.db.models  # noqa
from app.data.minute_store import MinuteStore


def _sess():
    e = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                      poolclass=StaticPool, future=True)
    Base.metadata.create_all(e)
    return sessionmaker(bind=e, future=True)()


def _row(hh, mm, c):
    return {"trade_time": datetime(2026, 6, 4, hh, mm), "open": c, "high": c,
            "low": c, "close": c, "vol": 100.0, "amount": 1000.0}


def test_upsert_get_and_last_time():
    s = _sess()
    st = MinuteStore(s)
    st.upsert("600519.SH", "1min", [_row(9, 30, 1650.0), _row(9, 31, 1651.0)])
    bars = st.get_bars("600519.SH", "1min", datetime(2026, 6, 4, 9, 0), datetime(2026, 6, 4, 15, 0))
    assert [b["c"] for b in bars] == [1650.0, 1651.0]      # 升序
    assert set(bars[0]) == {"t", "o", "h", "l", "c", "v"}
    assert st.last_time("600519.SH", "1min") == datetime(2026, 6, 4, 9, 31)


def test_upsert_idempotent_and_freq_isolated():
    s = _sess()
    st = MinuteStore(s)
    st.upsert("600519.SH", "1min", [_row(9, 30, 1650.0)])
    st.upsert("600519.SH", "1min", [_row(9, 30, 1660.0)])   # 同 PK → 更新
    st.upsert("600519.SH", "5min", [_row(9, 30, 9.0)])      # 不同 freq 隔离
    assert st.get_bars("600519.SH", "1min", datetime(2026,6,4,9,0), datetime(2026,6,4,15,0))[0]["c"] == 1660.0
    assert len(st.get_bars("600519.SH", "1min", datetime(2026,6,4,9,0), datetime(2026,6,4,15,0))) == 1
    assert st.last_time("600519.SH", "5min") == datetime(2026, 6, 4, 9, 30)
```

- [ ] **Step 2: 跑,确认 FAIL** — `.venv/bin/pytest tests/test_minute_store.py -v`

- [ ] **Step 3: 实现** — 在 `app/db/models.py` 顶部导入补 `DateTime`(加进 sqlalchemy import)和 `from datetime import date, datetime`;末尾追加:

```python
class MinuteQuote(Base):
    __tablename__ = "minute_quotes"
    code: Mapped[str] = mapped_column(String(16), primary_key=True)
    freq: Mapped[str] = mapped_column(String(8), primary_key=True)
    trade_time: Mapped[datetime] = mapped_column(DateTime, primary_key=True)
    open: Mapped[float] = mapped_column(Float)
    high: Mapped[float] = mapped_column(Float)
    low: Mapped[float] = mapped_column(Float)
    close: Mapped[float] = mapped_column(Float)
    vol: Mapped[float] = mapped_column(Float, default=0.0)
    amount: Mapped[float] = mapped_column(Float, default=0.0)


Index("ix_minute_quotes_ck", MinuteQuote.code, MinuteQuote.freq, MinuteQuote.trade_time)
```

`app/data/minute_store.py`:

```python
from datetime import datetime
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from app.db.models import MinuteQuote


class MinuteStore:
    def __init__(self, session: Session):
        self.s = session

    def upsert(self, code: str, freq: str, rows: list[dict]) -> None:
        for r in rows:
            self.s.merge(MinuteQuote(code=code, freq=freq, **r))
        self.s.commit()

    def get_bars(self, code: str, freq: str, start: datetime, end: datetime) -> list[dict]:
        rows = self.s.scalars(
            select(MinuteQuote).where(
                MinuteQuote.code == code, MinuteQuote.freq == freq,
                MinuteQuote.trade_time >= start, MinuteQuote.trade_time <= end)
            .order_by(MinuteQuote.trade_time)).all()
        return [{"t": r.trade_time, "o": r.open, "h": r.high, "l": r.low,
                 "c": r.close, "v": r.vol} for r in rows]

    def last_time(self, code: str, freq: str):
        return self.s.scalar(select(func.max(MinuteQuote.trade_time)).where(
            MinuteQuote.code == code, MinuteQuote.freq == freq))
```

- [ ] **Step 4: 跑,确认 PASS** — `.venv/bin/pytest tests/test_minute_store.py -v`
- [ ] **Step 5: Commit** — `git add app/db/models.py app/data/minute_store.py tests/test_minute_store.py && git commit -m "feat(data): MinuteQuote table + MinuteStore"`

---

### Task 2: MinuteFetcher(tushare stk_mins,限频注入)

**Files:** Create `app/data/minute_fetch.py`;Test `tests/test_minute_fetch.py`

- [ ] **Step 1: 写测试** `tests/test_minute_fetch.py`:

```python
from datetime import datetime
import pandas as pd
from app.data.minute_fetch import MinuteFetcher


class FakePro:
    def __init__(self, df=None, raise_=False):
        self._df = df; self._raise = raise_; self.calls = []
    def stk_mins(self, **kw):
        self.calls.append(kw)
        if self._raise:
            raise RuntimeError("rate limit")
        return self._df


def _df():
    return pd.DataFrame([
        {"ts_code": "600519.SH", "trade_time": "2026-06-04 09:30:00", "open": 1650.0,
         "high": 1652.0, "low": 1649.0, "close": 1651.0, "vol": 100.0, "amount": 1000.0},
    ])


def test_fetch_maps_rows():
    pro = FakePro(_df())
    rows = MinuteFetcher(pro).fetch("600519.SH", "1min", "2026-06-04 09:30:00", "2026-06-04 15:00:00")
    assert len(rows) == 1
    r = rows[0]
    assert r["trade_time"] == datetime(2026, 6, 4, 9, 30)
    assert r["open"] == 1650.0 and r["close"] == 1651.0 and r["vol"] == 100.0
    assert pro.calls[0]["ts_code"] == "600519.SH" and pro.calls[0]["freq"] == "1min"


def test_fetch_error_returns_empty():
    assert MinuteFetcher(FakePro(raise_=True)).fetch("x", "1min", "a", "b") == []


def test_fetch_empty_df_returns_empty():
    assert MinuteFetcher(FakePro(pd.DataFrame())).fetch("x", "1min", "a", "b") == []
```

- [ ] **Step 2: 跑,确认 FAIL** — `.venv/bin/pytest tests/test_minute_fetch.py -v`

- [ ] **Step 3: 实现** `app/data/minute_fetch.py`:

```python
from datetime import datetime


class MinuteFetcher:
    def __init__(self, pro, limiter=None):
        self.pro = pro
        self.limiter = limiter

    def fetch(self, code: str, freq: str, start: str, end: str) -> list[dict]:
        if self.limiter is not None:
            self.limiter.acquire()
        try:
            df = self.pro.stk_mins(ts_code=code, freq=freq, start_date=start, end_date=end)
        except Exception:
            return []
        if df is None or len(df) == 0:
            return []
        out = []
        for r in df.itertuples(index=False):
            out.append({
                "trade_time": datetime.strptime(str(r.trade_time), "%Y-%m-%d %H:%M:%S"),
                "open": float(r.open), "high": float(r.high), "low": float(r.low),
                "close": float(r.close), "vol": float(r.vol), "amount": float(r.amount)})
        return out
```

- [ ] **Step 4: 跑,确认 PASS** — `.venv/bin/pytest tests/test_minute_fetch.py -v`
- [ ] **Step 5: Commit** — `git add app/data/minute_fetch.py tests/test_minute_fetch.py && git commit -m "feat(data): MinuteFetcher via tushare stk_mins (rate-limited)"`

---

### Task 3: minute_universe(关注股并集)

**Files:** Create `app/data/minute_universe.py`;Test `tests/test_minute_universe.py`

- [ ] **Step 1: 写测试** `tests/test_minute_universe.py`:

```python
from datetime import date
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.db.database import Base
import app.db.models  # noqa
from app.db.models import Position, Decision, TrackEntry, DecisionJob, Account
from app.data.minute_universe import minute_universe


def _sess():
    e = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                      poolclass=StaticPool, future=True)
    Base.metadata.create_all(e)
    return sessionmaker(bind=e, future=True)()


def test_universe_is_dedup_union():
    s = _sess()
    s.add(Account(id=1, name="m", cash=1.0))
    s.add(Position(account_id=1, code="600519.SH", shares=1, cost=1.0))
    s.add(TrackEntry(code="000001.SZ", added_on=date(2026, 6, 1), name="平安", entry_close=1.0))
    s.add(Decision(as_of=date(2026, 6, 4), code="600519.SH", action="HOLD", confidence=0.5,
                   shares=0, reasoning="", status="APPROVED", created_at=date(2026, 6, 4)))
    s.add(DecisionJob(code="300285.SZ", status="DONE", created_at=date(2026, 6, 4)))
    s.commit()
    assert minute_universe(s) == ["000001.SZ", "300285.SZ", "600519.SH"]   # 去重+排序
```

- [ ] **Step 2: 跑,确认 FAIL** — `.venv/bin/pytest tests/test_minute_universe.py -v`

- [ ] **Step 3: 实现** `app/data/minute_universe.py`:

```python
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.db.models import Position, Decision, TrackEntry, DecisionJob


def minute_universe(session: Session) -> list[str]:
    codes: set[str] = set()
    for model in (Position, Decision, TrackEntry, DecisionJob):
        codes.update(session.scalars(select(model.code)).all())
    return sorted(c for c in codes if c)
```

- [ ] **Step 4: 跑,确认 PASS** — `.venv/bin/pytest tests/test_minute_universe.py -v`
- [ ] **Step 5: Commit** — `git add app/data/minute_universe.py tests/test_minute_universe.py && git commit -m "feat(data): minute_universe (watchlist union)"`

---

### Task 4: 采集核心 update_codes + 守护脚本

**Files:** Create `app/data/minute_updater.py`、`scripts/minute_updater_daemon.py`;Test `tests/test_minute_updater.py`

- [ ] **Step 1: 写测试** `tests/test_minute_updater.py`:

```python
from datetime import date, datetime
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.db.database import Base
import app.db.models  # noqa
from app.data.minute_store import MinuteStore
from app.data.minute_updater import update_codes, in_market_hours


class FakeFetcher:
    def __init__(self): self.calls = []
    def fetch(self, code, freq, start, end):
        self.calls.append((code, freq, start, end))
        # 返回当日两根
        return [{"trade_time": datetime(2026, 6, 4, 9, 30), "open": 1.0, "high": 1.0,
                 "low": 1.0, "close": 1.0, "vol": 1.0, "amount": 1.0},
                {"trade_time": datetime(2026, 6, 4, 9, 31), "open": 2.0, "high": 2.0,
                 "low": 2.0, "close": 2.0, "vol": 1.0, "amount": 1.0}]


def _sess():
    e = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                      poolclass=StaticPool, future=True)
    Base.metadata.create_all(e)
    return sessionmaker(bind=e, future=True)()


def test_update_codes_fetches_and_upserts():
    s = _sess(); store = MinuteStore(s); f = FakeFetcher()
    n = update_codes(s, f, store, ["600519.SH"], freq="1min", today=date(2026, 6, 4))
    assert n == 2
    assert store.last_time("600519.SH", "1min") == datetime(2026, 6, 4, 9, 31)
    # 第二轮:start 应在上次 last_time 之后
    update_codes(s, f, store, ["600519.SH"], freq="1min", today=date(2026, 6, 4))
    assert f.calls[1][2] == "2026-06-04 09:32:00"   # last_time + 1min


def test_in_market_hours():
    assert in_market_hours(datetime(2026, 6, 4, 10, 0))    # 上午盘
    assert in_market_hours(datetime(2026, 6, 4, 14, 0))    # 下午盘
    assert not in_market_hours(datetime(2026, 6, 4, 12, 0))  # 午休
    assert not in_market_hours(datetime(2026, 6, 4, 16, 0))  # 收盘后
```

- [ ] **Step 2: 跑,确认 FAIL** — `.venv/bin/pytest tests/test_minute_updater.py -v`

- [ ] **Step 3: 实现** `app/data/minute_updater.py`:

```python
from datetime import date, datetime, timedelta, time


def in_market_hours(dt: datetime) -> bool:
    t = dt.time()
    return (time(9, 30) <= t <= time(11, 30)) or (time(13, 0) <= t <= time(15, 0))


def update_codes(session, fetcher, store, codes, freq: str = "1min", today: date | None = None) -> int:
    today = today or date.today()
    open_dt = datetime(today.year, today.month, today.day, 9, 30)
    end_s = datetime(today.year, today.month, today.day, 15, 0).strftime("%Y-%m-%d %H:%M:%S")
    total = 0
    for code in codes:
        last = store.last_time(code, freq)
        start = (last + timedelta(minutes=1)) if last else open_dt
        rows = fetcher.fetch(code, freq, start.strftime("%Y-%m-%d %H:%M:%S"), end_s)
        if rows:
            store.upsert(code, freq, rows)
            total += len(rows)
    return total
```

`scripts/minute_updater_daemon.py`:

```python
"""盘中分钟采集守护:对关注股 round-robin 增量采集进库(stk_mins 全局 1/min)。
用法:setsid python scripts/minute_updater_daemon.py"""
import sys, time as _time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import tushare as ts
from app.config import get_settings
from app.db.database import make_engine, make_session_factory, Base
import app.db.models  # noqa: F401
from app.data.minute_store import MinuteStore
from app.data.minute_fetch import MinuteFetcher
from app.data.minute_universe import minute_universe
from app.data.minute_updater import update_codes, in_market_hours
from app.data.rate_limiter import RateLimiter


def main():
    s = get_settings()
    engine = make_engine(); Base.metadata.create_all(engine)
    session = make_session_factory(engine)()
    pro = ts.pro_api(s.tushare_token)
    fetcher = MinuteFetcher(pro, limiter=RateLimiter(1, 60))   # 接口 1/min
    store = MinuteStore(session)
    print("MINUTE_UPDATER_START", flush=True)
    while True:
        now = datetime.now()
        if in_market_hours(now):
            codes = minute_universe(session)
            n = update_codes(session, fetcher, store, codes, freq="1min")
            print(f"[{now.isoformat()}] universe={len(codes)} upserted={n}", flush=True)
        else:
            _time.sleep(60)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: 跑,确认 PASS** — `.venv/bin/pytest tests/test_minute_updater.py -v`
- [ ] **Step 5: Commit** — `git add app/data/minute_updater.py scripts/minute_updater_daemon.py tests/test_minute_updater.py && git commit -m "feat(data): minute updater core + daemon"`

---

### Task 5: GET /api/kline 端点(只读库)

**Files:** Create `app/api/routes_kline.py`;Modify `app/main.py`;Test `tests/test_api_kline.py`

- [ ] **Step 1: 写测试** `tests/test_api_kline.py`:

```python
from datetime import datetime
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.db.database import Base
import app.db.models  # noqa
from app.db.models import StockName
from app.data.minute_store import MinuteStore
from app.main import create_app
from app.api.deps import get_session


def _client():
    e = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                      poolclass=StaticPool, future=True)
    Base.metadata.create_all(e)
    s = sessionmaker(bind=e, future=True)()
    s.add(StockName(code="600519.SH", name="贵州茅台")); s.commit()
    MinuteStore(s).upsert("600519.SH", "1min", [
        {"trade_time": datetime(2026, 6, 4, 9, 30), "open": 1650.0, "high": 1652.0,
         "low": 1649.0, "close": 1651.0, "vol": 100.0, "amount": 1000.0}])
    app = create_app()
    app.dependency_overrides[get_session] = lambda: s
    return TestClient(app), s


def test_kline_reads_from_db():
    client, _ = _client()
    body = client.get("/api/kline/600519.SH?freq=1min&days=30").json()
    assert body["code"] == "600519.SH" and body["name"] == "贵州茅台" and body["freq"] == "1min"
    assert len(body["bars"]) == 1
    b = body["bars"][0]
    assert b["o"] == 1650.0 and b["c"] == 1651.0 and "t" in b
    assert body["last_time"] is not None


def test_kline_empty_when_uncached():
    client, _ = _client()
    body = client.get("/api/kline/000001.SZ?freq=1min").json()
    assert body["bars"] == [] and body["last_time"] is None
```

- [ ] **Step 2: 跑,确认 FAIL** — `.venv/bin/pytest tests/test_api_kline.py -v`

- [ ] **Step 3: 实现** `app/api/routes_kline.py`:

```python
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.api.deps import get_session
from app.data.minute_store import MinuteStore
from app.data.names import NameLookup

router = APIRouter(prefix="/api", tags=["kline"])


@router.get("/kline/{code}")
def get_kline(code: str, freq: str = "1min", days: int = 2, s: Session = Depends(get_session)):
    store = MinuteStore(s)
    end = datetime.now()
    start = end - timedelta(days=days + 5)
    bars = store.get_bars(code, freq, start, end)
    last = store.last_time(code, freq)
    return {"code": code, "name": NameLookup(s).get(code), "freq": freq,
            "bars": [{"t": b["t"].isoformat(), "o": b["o"], "h": b["h"],
                      "l": b["l"], "c": b["c"], "v": b["v"]} for b in bars],
            "last_time": last.isoformat() if last else None}
```

`app/main.py`:在其它 `from app.api import ...` / `app.include_router(...)` 处加 `routes_kline` 的 import 与 `app.include_router(routes_kline.router)`(放在 routes_tracklist 之后)。

- [ ] **Step 4: 跑,确认 PASS** — `.venv/bin/pytest tests/test_api_kline.py -v`
- [ ] **Step 5: Commit** — `git add app/api/routes_kline.py app/main.py tests/test_api_kline.py && git commit -m "feat(api): GET /api/kline reads minute bars from DB"`

---

### Task 6: 前端 KLineChart 组件(klinecharts)

**Files:** `frontend/package.json`(加依赖);Create `src/components/KLineChart.tsx`;Test `src/components/KLineChart.test.tsx`

- [ ] **Step 1: 装依赖** — `cd frontend && npm i klinecharts`(报告安装的版本)。

- [ ] **Step 2: 写测试** `src/components/KLineChart.test.tsx`(mock klinecharts 避免 jsdom canvas 问题):

```tsx
import { render } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";

const applyNewData = vi.fn();
vi.mock("klinecharts", () => ({
  init: () => ({ applyNewData }),
  dispose: vi.fn(),
}));

import { KLineChart } from "./KLineChart";

describe("KLineChart", () => {
  it("feeds bars to the chart without crashing", () => {
    const bars = [{ t: "2026-06-04T09:30:00", o: 1, h: 2, l: 0.5, c: 1.5, v: 10 }];
    const { container } = render(<KLineChart bars={bars as any} />);
    expect(container.querySelector("div")).toBeTruthy();
    expect(applyNewData).toHaveBeenCalled();
  });
});
```

- [ ] **Step 3: 跑,确认 FAIL** — `npx vitest run src/components/KLineChart.test.tsx`

- [ ] **Step 4: 实现** `src/components/KLineChart.tsx`:

```tsx
import { useEffect, useRef } from "react";
import { init, dispose } from "klinecharts";

export type Bar = { t: string; o: number; h: number; l: number; c: number; v: number };

export function KLineChart({ bars }: { bars: Bar[] }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!ref.current) return;
    const chart = init(ref.current);
    chart?.applyNewData(bars.map((b) => ({
      timestamp: new Date(b.t).getTime(),
      open: b.o, high: b.h, low: b.l, close: b.c, volume: b.v,
    })));
    return () => { if (ref.current) dispose(ref.current); };
  }, [bars]);
  return <div ref={ref} style={{ width: "100%", height: 360 }} />;
}
```

- [ ] **Step 5: 跑,确认 PASS** — `npx vitest run src/components/KLineChart.test.tsx`;`npx tsc --noEmit` 干净。
- [ ] **Step 6: Commit** — `git add frontend/package.json frontend/package-lock.json src/components/KLineChart.tsx src/components/KLineChart.test.tsx && git commit -m "feat(frontend): KLineChart (klinecharts wrapper)"`

---

### Task 7: 全局图表 Provider/Modal + StockLink

**Files:** Create `src/components/{StockChartProvider,StockChartModal,StockLink}.tsx`;Modify `src/main.tsx`;Test `src/components/StockLink.test.tsx`

- [ ] **Step 1: 写测试** `src/components/StockLink.test.tsx`(整链:Provider+Link,点击弹出 Modal 并拉数据):

```tsx
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { StockChartProvider } from "./StockChartProvider";
import { StockLink } from "./StockLink";

vi.mock("./KLineChart", () => ({ KLineChart: () => <div data-testid="kline" /> }));

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn(() => Promise.resolve({ ok: true,
    json: () => Promise.resolve({ code: "600519.SH", name: "贵州茅台", freq: "1min",
      bars: [], last_time: null }) })) as any);
});

describe("StockLink + provider", () => {
  it("clicking a StockLink opens the chart modal", async () => {
    render(<StockChartProvider><StockLink code="600519.SH" name="贵州茅台" /></StockChartProvider>);
    fireEvent.click(screen.getByText(/贵州茅台/));
    await waitFor(() => expect(screen.getByTestId("kline")).toBeInTheDocument());
    expect(screen.getAllByText(/600519\.SH/).length).toBeGreaterThan(0);
  });
});
```

- [ ] **Step 2: 跑,确认 FAIL** — `npx vitest run src/components/StockLink.test.tsx`

- [ ] **Step 3: 实现**
`src/components/StockChartProvider.tsx`:

```tsx
import { createContext, useContext, useState, useCallback, type ReactNode } from "react";
import { StockChartModal } from "./StockChartModal";

type Ctx = { openChart: (code: string, name?: string) => void };
const ChartCtx = createContext<Ctx>({ openChart: () => {} });
export const useStockChart = () => useContext(ChartCtx);

export function StockChartProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<{ code: string; name?: string } | null>(null);
  const openChart = useCallback((code: string, name?: string) => setState({ code, name }), []);
  return (
    <ChartCtx.Provider value={{ openChart }}>
      {children}
      <StockChartModal code={state?.code ?? null} name={state?.name}
        onClose={() => setState(null)} />
    </ChartCtx.Provider>
  );
}
```

`src/components/StockChartModal.tsx`:

```tsx
import { useEffect, useState, useCallback } from "react";
import { Modal, Segmented } from "antd";
import { apiGet } from "../api/client";
import { KLineChart, type Bar } from "./KLineChart";

const FREQS = ["1min", "5min", "15min", "30min", "60min"];

export function StockChartModal({ code, name, onClose }:
  { code: string | null; name?: string; onClose: () => void }) {
  const [freq, setFreq] = useState("1min");
  const [bars, setBars] = useState<Bar[]>([]);
  const load = useCallback(() => {
    if (!code) return;
    apiGet<{ bars: Bar[] }>(`/api/kline/${code}?freq=${freq}`).then((d) => setBars(d.bars)).catch(() => {});
  }, [code, freq]);
  useEffect(() => { load(); }, [load]);
  useEffect(() => {
    if (!code) return;
    const t = setInterval(load, 60000);
    return () => clearInterval(t);
  }, [code, load]);

  return (
    <Modal open={!!code} onCancel={onClose} footer={null} width={900}
      title={`${name ? name + " " : ""}${code ?? ""} 分钟K线`}>
      <Segmented options={FREQS} value={freq} onChange={(v) => setFreq(v as string)} />
      <div style={{ marginTop: 12 }}>
        {bars.length ? <KLineChart bars={bars} /> : <div style={{ padding: 40, textAlign: "center" }}>采集中…</div>}
      </div>
    </Modal>
  );
}
```

`src/components/StockLink.tsx`:

```tsx
import { useStockChart } from "./StockChartProvider";

export function StockLink({ code, name }: { code: string; name?: string }) {
  const { openChart } = useStockChart();
  return (
    <a onClick={(e) => { e.stopPropagation(); openChart(code, name); }}>
      {name ? `${name}(${code})` : code}
    </a>
  );
}
```

- [ ] **Step 4: 跑,确认 PASS** — `npx vitest run src/components/StockLink.test.tsx`

- [ ] **Step 5: 接 main.tsx** — 在 `src/main.tsx` 用 `<StockChartProvider>` 包 `<App/>`(放在 `ThemeProvider` 内、`App` 外)。import StockChartProvider。

- [ ] **Step 6: 验证 + Commit** — `npx vitest run src/components/StockLink.test.tsx && npx tsc --noEmit`;
`git add src/components/StockChartProvider.tsx src/components/StockChartModal.tsx src/components/StockLink.tsx src/main.tsx && git commit -m "feat(frontend): global StockChart modal + StockLink + provider"`

---

### Task 8: 各列表接 StockLink + 全量验证 + 部署

**Files:** Modify `src/components/{PositionsTable,PicksTable,DiscoveryPanel,TrackTable}.tsx`、`src/pages/{DecisionsPage,ResearchPage}.tsx`

- [ ] **Step 1: 替换股票名显示为 StockLink** — 这些位置当前显示 `名称(代码)` 纯文本(Task 12 of 上个特性已统一);把它们换成 `<StockLink code={r.code} name={r.name} />`:
  - `PositionsTable.tsx`(renderCard 的 `<b>{p.name||p.code}</b>` 与桌面 名称列)
  - `PicksTable.tsx`、`DiscoveryPanel.tsx`、`TrackTable.tsx`(各 renderCard 首项 + 桌面首列 render)
  - `DecisionsPage.tsx`(列表 renderCard + 代码列 render)、`ResearchPage.tsx`(同)
  import `StockLink` from "../components/StockLink"(页面文件用相对路径)。**保留各列表 onRowClick**;StockLink 内已 `stopPropagation`,点名称只弹图、不触发选中。

- [ ] **Step 2: 全量前端测试** — `npx vitest run`。若某列表测试因首列从纯文本变成 `<a>` 链接而选择器失配,用 `getByText(/代码/)` 正则或 `getByRole("link")` 调整,不弱化覆盖。注意:用到 StockLink 的列表测试需要包在 `StockChartProvider` 里(否则 useStockChart 用默认空实现也不报错——StockLink 不强依赖 Provider,默认 openChart 为 noop,故现有列表测试无需包 Provider 即可渲染)。

- [ ] **Step 3: 全量后端测试** — `cd backend && .venv/bin/pytest -q`,全绿。

- [ ] **Step 4: 构建** — `cd frontend && VITE_API_BASE="" npm run build`,exit 0。

- [ ] **Step 5: 部署** —
  - 建表+重启后端:`cd backend && pkill -f 'uvicorn app.main'; sleep 1; setsid bash -c '.venv/bin/python -c "from app.db.database import make_engine,Base; import app.db.models; Base.metadata.create_all(make_engine())"; .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000 > /tmp/ashare_uvicorn.log 2>&1' </dev/null &`
  - 启动采集守护:`cd backend && setsid bash -c '.venv/bin/python scripts/minute_updater_daemon.py > /tmp/minute_updater.log 2>&1' </dev/null &`
  - `cd /root/caddy && ./caddy reload --config Caddyfile`
  - 验证:`curl -s --noproxy '*' http://localhost:8000/api/kline/600519.SH?freq=1min | head -c 200`(盘中守护跑过后应有 bars)。

- [ ] **Step 6: Commit** — `git add src/components/PositionsTable.tsx src/components/PicksTable.tsx src/components/DiscoveryPanel.tsx src/components/TrackTable.tsx src/pages/DecisionsPage.tsx src/pages/ResearchPage.tsx && git commit -m "feat(frontend): clickable StockLink across all stock lists"`

---

## 备注
- `stk_mins` 全局 1/min → universe N 只时每只约每 N 分钟刷一次;非实时,尽力而为。
- 端点只读库、不调 tushare → 前端与采集解耦,响应快。
- 守护与 uvicorn/caddy 同属后台,容器重启需重拉(待办统一 start_all.sh)。
- 不用 qlib 存分钟(SQL 表足够);qlib 分钟留待将来做分钟因子/回测。
