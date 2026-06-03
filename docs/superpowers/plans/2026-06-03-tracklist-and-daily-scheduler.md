# 跟踪表 + 每日定时更新 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让用户粘贴一张股票列表后系统持续跟踪其后续走势(T+1/3/5/10 + 至今/最大涨幅/最大回撤),并每天 16:00(北京时间)自动更新全市场行情、qlib 与跟踪表。

**Architecture:** 新增独立 `tracklist` 表与 `Tracker` 服务(沿用 `WatchPool` 模式,对传入的日线序列计算指标,口径与 `WatchPool` 一致使用原始收盘价);文本解析器把同花顺粘贴文本转成 (code, name);新 REST 路由 `/api/track`;前端新增"跟踪"页;编排脚本 `daily_full.py` 串联行情→qlib→跟踪表;后端用 APScheduler 在 startup 注册每天 16:00 Asia/Shanghai 的 job。

**Tech Stack:** Python / FastAPI / SQLAlchemy 2.0 / pytest;APScheduler;React + Ant Design + Vite;tushare + pyqlib(沿用现有脚本)。

**Note(对 spec 的偏差):** 指标口径采用**原始收盘价**(与现有 `WatchPool.update_forward_returns` 一致),而非 spec 写的后复权。短周期、个人 MVP 下足够;后复权列为后续改进。

---

## File Structure

后端(`backend/`):
- Create `app/screener/tracklist_parser.py` — 纯函数解析粘贴文本 → `list[tuple[str,str]]`
- Create `app/screener/tracklist.py` — `Tracker` 服务(add/update_metrics/list/remove)
- Create `app/api/routes_tracklist.py` — `/api/track` 路由
- Create `scripts/daily_full.py` — 编排:行情→qlib→跟踪表;含可调度入口 `run_all()`
- Create `app/scheduler.py` — APScheduler 注册逻辑
- Modify `app/db/models.py` — 新增 `TrackEntry` 模型
- Modify `app/api/__init__.py` 无需改;`app/main.py` — 注册路由 + 启动调度器
- Modify `app/config.py` — 新增 `enable_scheduler` / `daily_update_hour` 设置
- Modify `pyproject.toml` — 增加 `apscheduler` 依赖
- Tests: `tests/test_tracklist_parser.py`, `tests/test_tracklist.py`, `tests/test_api_tracklist.py`, `tests/test_daily_full.py`, `tests/test_scheduler.py`

前端(`frontend/`):
- Create `src/pages/TrackPage.tsx`
- Create `src/components/TrackTable.tsx`
- Create `src/pages/TrackPage.test.tsx`
- Modify `src/api/client.ts` — 增加 `apiDelete`
- Modify `src/App.tsx` — 增加菜单项与路由

---

## Task 1: TrackEntry 数据模型

**Files:**
- Modify: `backend/app/db/models.py`
- Test: `backend/tests/test_tracklist.py`

- [ ] **Step 1: 写失败测试(模型可建表+插入)**

```python
# backend/tests/test_tracklist.py
from datetime import date
from app.db.models import TrackEntry


def test_track_entry_persists(session):
    e = TrackEntry(code="300975", added_on=date(2026, 6, 3), name="商络电子",
                   entry_close=43.41)
    session.add(e); session.commit()
    got = session.get(TrackEntry, ("300975", date(2026, 6, 3)))
    assert got.name == "商络电子"
    assert got.entry_close == 43.41
    assert got.ret_t1 is None and got.max_drawdown is None
```

- [ ] **Step 2: 运行,确认失败**

Run: `cd backend && .venv/bin/pytest tests/test_tracklist.py::test_track_entry_persists -v`
Expected: FAIL — `ImportError: cannot import name 'TrackEntry'`

- [ ] **Step 3: 新增模型**

在 `backend/app/db/models.py` 末尾(`BacktestRun` 之后、文件结尾)追加:

```python
class TrackEntry(Base):
    __tablename__ = "tracklist"
    code: Mapped[str] = mapped_column(String(16), primary_key=True)
    added_on: Mapped[date] = mapped_column(Date, primary_key=True)
    name: Mapped[str] = mapped_column(String(32), default="")
    entry_close: Mapped[float] = mapped_column(Float)
    ret_t1: Mapped[float | None] = mapped_column(Float, nullable=True)
    ret_t3: Mapped[float | None] = mapped_column(Float, nullable=True)
    ret_t5: Mapped[float | None] = mapped_column(Float, nullable=True)
    ret_t10: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_close: Mapped[float | None] = mapped_column(Float, nullable=True)
    ret_since: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_gain: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_drawdown: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_updated: Mapped[date | None] = mapped_column(Date, nullable=True)
```

- [ ] **Step 4: 运行,确认通过**

Run: `cd backend && .venv/bin/pytest tests/test_tracklist.py::test_track_entry_persists -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add backend/app/db/models.py backend/tests/test_tracklist.py
git commit -m "feat(track): add TrackEntry model"
```

---

## Task 2: 同花顺文本解析器

**Files:**
- Create: `backend/app/screener/tracklist_parser.py`
- Test: `backend/tests/test_tracklist_parser.py`

- [ ] **Step 1: 写失败测试(用真实粘贴样例)**

```python
# backend/tests/test_tracklist_parser.py
from app.screener.tracklist_parser import parse_tracklist

SAMPLE = """
19:51    同花顺App
同花顺自选
4075.10+17.36
上证指数+0.43%
最新    涨幅    现手
商络电子    43.41    +12.72%    4
融    300975
福达合金    75.26    +10.00%    86
融    603045
大唐发电    601991    9.18    +9.68%    16.6万
江丰电子    209.22    +11.25%
300666
力源信息    18.26    +15.13%
融    300184
南亚新材    238.92    +10.33%    5
融    688519
新锐股份    98.21    +8.20%
融    688257
雅创电子    71.47    +10.40%    1533
融    301099
凯格精机    258.44    +10.21%
融    301338
东杰智能    29.98    +20.02%    12
创    300486
"""


def test_parse_extracts_ten_codes():
    out = parse_tracklist(SAMPLE)
    codes = [c for c, _ in out]
    assert codes == ["300975", "603045", "601991", "300666", "300184",
                     "688519", "688257", "301099", "301338", "300486"]


def test_parse_pairs_names():
    out = dict(parse_tracklist(SAMPLE))
    assert out["300975"] == "商络电子"
    assert out["601991"] == "大唐发电"   # 名称与代码同行
    assert out["300666"] == "江丰电子"   # 名称在代码上一行


def test_parse_dedups_and_ignores_index_numbers():
    # 4075.10 / 0.43 等带小数点的数字不是 6 位代码;指数行不应混入
    out = parse_tracklist(SAMPLE)
    assert len(out) == 10
    assert all(c.isdigit() and len(c) == 6 for c, _ in out)


def test_parse_empty():
    assert parse_tracklist("没有任何代码") == []
```

- [ ] **Step 2: 运行,确认失败**

Run: `cd backend && .venv/bin/pytest tests/test_tracklist_parser.py -v`
Expected: FAIL — `ModuleNotFoundError: app.screener.tracklist_parser`

- [ ] **Step 3: 实现解析器**

```python
# backend/app/screener/tracklist_parser.py
"""把同花顺自选页粘贴的文本解析为 [(code, name)]。

策略:逐行扫描,用正则找出独立的 6 位数字作为 A 股代码(\b 边界,避免匹配
4075.10 这类带小数的数字);名称取代码所在行的中文词,若该行没有中文,则回退
到上一行的中文词(同花顺常把名称放在代码上一行)。去重,保留首次出现顺序。
"""
import re

_CODE = re.compile(r"(?<!\d)(\d{6})(?!\d)")
_NAME = re.compile(r"[一-鿿]{2,8}")
# 这些中文词是页面噪声,不是股票名
_STOP = {"同花顺", "同花顺App", "自选", "上证指数", "最新", "涨幅", "现手",
         "资金", "资讯", "资产", "分析", "全部", "沪深京", "港股", "美股",
         "期货", "基金", "首页", "行情", "交易", "理财"}


def _pick_name(text: str) -> str | None:
    for w in _NAME.findall(text):
        if w not in _STOP:
            return w
    return None


def parse_tracklist(text: str) -> list[tuple[str, str]]:
    lines = text.splitlines()
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    for i, line in enumerate(lines):
        for code in _CODE.findall(line):
            if code in seen:
                continue
            name = _pick_name(line)
            if name is None and i > 0:
                name = _pick_name(lines[i - 1])
            seen.add(code)
            out.append((code, name or ""))
    return out
```

- [ ] **Step 4: 运行,确认通过**

Run: `cd backend && .venv/bin/pytest tests/test_tracklist_parser.py -v`
Expected: PASS(4 个测试全过)

- [ ] **Step 5: 提交**

```bash
git add backend/app/screener/tracklist_parser.py backend/tests/test_tracklist_parser.py
git commit -m "feat(track): add THS tracklist text parser"
```

---

## Task 3: Tracker 服务

**Files:**
- Create: `backend/app/screener/tracklist.py`
- Test: `backend/tests/test_tracklist.py`(追加)

- [ ] **Step 1: 追加失败测试**

```python
# 追加到 backend/tests/test_tracklist.py 末尾
from app.data.source import DailyBar
from app.screener.tracklist import Tracker


def _bars(start_close, n=12):
    out = []
    for i in range(n):
        d = date(2026, 6, 3 + i)
        c = start_close + i
        out.append(DailyBar("X", d, c, c, c, c, 1000, 1.0))
    return out


def test_add_is_idempotent(session):
    t = Tracker(session)
    t.add([("X", "测试")], on=date(2026, 6, 3), closes={"X": 10.0})
    t.add([("X", "改名")], on=date(2026, 6, 3), closes={"X": 99.0})
    rows = t.list()
    assert len(rows) == 1
    assert rows[0].entry_close == 10.0 and rows[0].name == "测试"


def test_add_skips_codes_without_close(session):
    t = Tracker(session)
    added = t.add([("X", "有"), ("Y", "无")], on=date(2026, 6, 3),
                  closes={"X": 10.0})
    assert [e.code for e in added] == ["X"]


def test_update_metrics(session):
    t = Tracker(session)
    t.add([("X", "测试")], on=date(2026, 6, 3), closes={"X": 10.0})
    # 收盘 10,11,...,21;T+1=11,T+3=13,T+5=15,T+10=20;末日=21
    t.update_metrics("X", date(2026, 6, 3), _bars(10.0))
    e = t.list()[0]
    assert abs(e.ret_t1 - 0.1) < 1e-9
    assert abs(e.ret_t3 - 0.3) < 1e-9
    assert abs(e.ret_t5 - 0.5) < 1e-9
    assert abs(e.ret_t10 - 1.0) < 1e-9
    assert abs(e.last_close - 21.0) < 1e-9
    assert abs(e.ret_since - 1.1) < 1e-9          # 21/10 - 1
    assert abs(e.max_gain - 1.1) < 1e-9           # 单调上涨,峰值即末日
    assert e.last_updated == date(2026, 6, 14)


def test_update_metrics_drawdown(session):
    t = Tracker(session)
    t.add([("X", "测试")], on=date(2026, 6, 3), closes={"X": 10.0})
    # 收盘:10,12,9  -> 峰值12后跌到9,最大回撤 (9-12)/12 = -0.25
    bars = [DailyBar("X", date(2026, 6, 3), 10, 10, 10, 10, 1, 1.0),
            DailyBar("X", date(2026, 6, 4), 12, 12, 12, 12, 1, 1.0),
            DailyBar("X", date(2026, 6, 5), 9, 9, 9, 9, 1, 1.0)]
    t.update_metrics("X", date(2026, 6, 3), bars)
    e = t.list()[0]
    assert abs(e.max_gain - 0.2) < 1e-9           # 12/10 - 1
    assert abs(e.max_drawdown - (-0.25)) < 1e-9


def test_remove(session):
    t = Tracker(session)
    t.add([("X", "测试")], on=date(2026, 6, 3), closes={"X": 10.0})
    t.remove("X", date(2026, 6, 3))
    assert t.list() == []
```

- [ ] **Step 2: 运行,确认失败**

Run: `cd backend && .venv/bin/pytest tests/test_tracklist.py -v`
Expected: FAIL — `ModuleNotFoundError: app.screener.tracklist`

- [ ] **Step 3: 实现 Tracker**

```python
# backend/app/screener/tracklist.py
from datetime import date
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.db.models import TrackEntry
from app.data.source import DailyBar
from app.screener.filters import forward_return

_OFFSETS = {"ret_t1": 1, "ret_t3": 3, "ret_t5": 5, "ret_t10": 10}


class Tracker:
    def __init__(self, session: Session):
        self.s = session

    def get(self, code: str, on: date) -> TrackEntry | None:
        return self.s.get(TrackEntry, (code, on))

    def add(self, codes_with_names: list[tuple[str, str]], on: date,
            closes: dict[str, float]) -> list[TrackEntry]:
        """写入条目;跳过无收盘价的代码;同 (code,on) 已存在则保留首次。"""
        added: list[TrackEntry] = []
        for code, name in codes_with_names:
            if code not in closes:
                continue
            if self.get(code, on) is not None:
                continue
            e = TrackEntry(code=code, added_on=on, name=name,
                           entry_close=closes[code])
            self.s.add(e)
            added.append(e)
        self.s.commit()
        return added

    def update_metrics(self, code: str, on: date, bars: list[DailyBar]) -> None:
        e = self.get(code, on)
        if e is None:
            return
        closes = [b.close for b in bars if b.trade_date >= on]  # index0 == 入选日
        if not closes:
            return
        for field, n in _OFFSETS.items():
            fut = closes[n] if len(closes) > n else None
            setattr(e, field, forward_return(e.entry_close, fut))
        last = closes[-1]
        e.last_close = last
        e.ret_since = last / e.entry_close - 1.0
        # 后续序列(不含入选日)用于峰值/回撤
        future = closes[1:]
        if future:
            e.max_gain = max(c / e.entry_close - 1.0 for c in future)
            peak = closes[0]
            dd = 0.0
            for c in closes[1:]:
                peak = max(peak, c)
                dd = min(dd, c / peak - 1.0)
            e.max_drawdown = dd
        else:
            e.max_gain = 0.0
            e.max_drawdown = 0.0
        e.last_updated = bars[-1].trade_date if bars else on
        self.s.commit()

    def list(self) -> list[TrackEntry]:
        return list(self.s.scalars(
            select(TrackEntry).order_by(TrackEntry.added_on.desc(),
                                        TrackEntry.code)
        ).all())

    def remove(self, code: str, on: date) -> None:
        e = self.get(code, on)
        if e is not None:
            self.s.delete(e)
            self.s.commit()
```

- [ ] **Step 4: 运行,确认通过**

Run: `cd backend && .venv/bin/pytest tests/test_tracklist.py -v`
Expected: PASS(全部)

- [ ] **Step 5: 提交**

```bash
git add backend/app/screener/tracklist.py backend/tests/test_tracklist.py
git commit -m "feat(track): add Tracker service with forward/since/drawdown metrics"
```

---

## Task 4: /api/track 路由

**Files:**
- Create: `backend/app/api/routes_tracklist.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_api_tracklist.py`

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/test_api_tracklist.py
from datetime import date
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.db.database import Base
import app.db.models  # noqa: F401
from app.api import deps
from app.db.models import DailyQuote
from app.main import create_app


@pytest.fixture
def client():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    # 预置一条最新行情,作为入选日与入选价来源
    s = factory()
    s.add(DailyQuote(code="300975", trade_date=date(2026, 6, 3), close=43.41))
    s.commit(); s.close()

    def _override():
        s = factory()
        try:
            yield s
        finally:
            s.close()
    app = create_app()
    app.dependency_overrides[deps.get_session] = _override
    return TestClient(app)


def test_post_parses_and_adds(client):
    r = client.post("/api/track", json={"text": "商络电子 43.41\n融 300975"})
    assert r.status_code == 200
    body = r.json()
    assert body["added"][0]["code"] == "300975"
    assert body["added"][0]["entry_close"] == 43.41


def test_get_lists(client):
    client.post("/api/track", json={"text": "商络电子\n300975"})
    rows = client.get("/api/track").json()
    assert any(x["code"] == "300975" for x in rows)


def test_delete(client):
    client.post("/api/track", json={"text": "商络电子\n300975"})
    code = "300975"; on = "2026-06-03"
    assert client.delete(f"/api/track/{code}/{on}").status_code == 200
    assert client.get("/api/track").json() == []
```

注:`DailyQuote` 含 `trade_date`/`close` 等列(见 `app/db/models.py`),其余列可空或有默认。若构造报错,按模型补必填字段。

- [ ] **Step 2: 运行,确认失败**

Run: `cd backend && .venv/bin/pytest tests/test_api_tracklist.py -v`
Expected: FAIL — 404(路由未注册)

- [ ] **Step 3: 实现路由**

```python
# backend/app/api/routes_tracklist.py
from datetime import date
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select, desc
from sqlalchemy.orm import Session
from app.api.deps import get_session
from app.db.models import DailyQuote
from app.screener.tracklist import Tracker
from app.screener.tracklist_parser import parse_tracklist

router = APIRouter(prefix="/api/track", tags=["track"])


class AddReq(BaseModel):
    text: str


def _latest_trade_date(s: Session) -> date | None:
    return s.scalars(select(DailyQuote.trade_date)
                     .order_by(desc(DailyQuote.trade_date)).limit(1)).first()


def _row(e):
    return {"code": e.code, "name": e.name, "added_on": e.added_on.isoformat(),
            "entry_close": e.entry_close, "ret_t1": e.ret_t1, "ret_t3": e.ret_t3,
            "ret_t5": e.ret_t5, "ret_t10": e.ret_t10, "last_close": e.last_close,
            "ret_since": e.ret_since, "max_gain": e.max_gain,
            "max_drawdown": e.max_drawdown,
            "last_updated": e.last_updated.isoformat() if e.last_updated else None}


@router.post("")
def add(req: AddReq, s: Session = Depends(get_session)):
    on = _latest_trade_date(s)
    if on is None:
        return {"added": [], "error": "no market data"}
    pairs = parse_tracklist(req.text)
    codes = [c for c, _ in pairs]
    quotes = {q.code: q.close for q in s.scalars(
        select(DailyQuote).where(DailyQuote.code.in_(codes),
                                 DailyQuote.trade_date == on)).all()}
    added = Tracker(s).add(pairs, on=on, closes=quotes)
    return {"added": [_row(e) for e in added]}


@router.get("")
def list_all(s: Session = Depends(get_session)):
    return [_row(e) for e in Tracker(s).list()]


@router.delete("/{code}/{on}")
def remove(code: str, on: date, s: Session = Depends(get_session)):
    Tracker(s).remove(code, on)
    return {"ok": True}
```

- [ ] **Step 4: 注册路由**

修改 `backend/app/main.py`:把 import 行与 include 行各加一项。

import 块改为:
```python
    from app.api import (routes_account, routes_trade, routes_market,
                         routes_discovery, routes_decisions, routes_screener,
                         routes_research, routes_backtest, routes_tracklist)
```
在 `app.include_router(routes_backtest.router)` 之后加:
```python
    app.include_router(routes_tracklist.router)
```

- [ ] **Step 5: 运行,确认通过**

Run: `cd backend && .venv/bin/pytest tests/test_api_tracklist.py -v`
Expected: PASS(3 个)

- [ ] **Step 6: 提交**

```bash
git add backend/app/api/routes_tracklist.py backend/app/main.py backend/tests/test_api_tracklist.py
git commit -m "feat(track): add /api/track routes (add/list/delete)"
```

---

## Task 5: daily_full 编排脚本

**Files:**
- Create: `backend/scripts/daily_full.py`
- Test: `backend/tests/test_daily_full.py`

说明:`run_all()` 按顺序调用三个步骤函数 `step_quotes`/`step_qlib`/`step_tracklist`,每步包在 try/except 里,记录失败但继续。前两步用 `subprocess` 调已存在且可断点续跑、自带限频的脚本(`daily_update_quotes.py` / `build_qlib_data.py`);测试通过 monkeypatch 把三个步骤换成桩,验证顺序与"单步失败不中断"。

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/test_daily_full.py
import scripts.daily_full as df


def test_run_all_calls_steps_in_order(monkeypatch):
    calls = []
    monkeypatch.setattr(df, "step_quotes", lambda: calls.append("quotes"))
    monkeypatch.setattr(df, "step_qlib", lambda: calls.append("qlib"))
    monkeypatch.setattr(df, "step_tracklist", lambda: calls.append("track"))
    df.run_all()
    assert calls == ["quotes", "qlib", "track"]


def test_run_all_continues_on_failure(monkeypatch):
    calls = []

    def boom():
        raise RuntimeError("quotes failed")
    monkeypatch.setattr(df, "step_quotes", boom)
    monkeypatch.setattr(df, "step_qlib", lambda: calls.append("qlib"))
    monkeypatch.setattr(df, "step_tracklist", lambda: calls.append("track"))
    ok = df.run_all()
    assert calls == ["qlib", "track"]   # 后续步骤仍执行
    assert ok is False                  # 有失败 -> 返回 False
```

- [ ] **Step 2: 运行,确认失败**

Run: `cd backend && .venv/bin/pytest tests/test_daily_full.py -v`
Expected: FAIL — `ModuleNotFoundError: scripts.daily_full`

- [ ] **Step 3: 实现脚本**

```python
# backend/scripts/daily_full.py
"""每日编排:全市场行情 -> qlib 重建 -> 跟踪表指标刷新。
可命令行运行(python scripts/daily_full.py),也被 APScheduler 调用 run_all()。"""
import subprocess
import sys
import traceback
from pathlib import Path
from datetime import date

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import get_settings
from app.db.database import make_engine, make_session_factory
import app.db.models  # noqa: F401
from app.data.quote_store import QuoteStore
from app.screener.tracklist import Tracker

PY = sys.executable


def step_quotes() -> None:
    subprocess.run([PY, str(ROOT / "scripts" / "daily_update_quotes.py")],
                   cwd=ROOT, check=True)


def step_qlib() -> None:
    s = get_settings()
    subprocess.run([PY, str(ROOT / "scripts" / "build_qlib_data.py"),
                    "--qlib-dir", s.qlib_data_dir], cwd=ROOT, check=True)


def step_tracklist() -> None:
    session = make_session_factory(make_engine())()
    store = QuoteStore(session)
    tr = Tracker(session)
    for e in tr.list():
        bars = store.get_bars(e.code, e.added_on, date.today())
        if bars:
            tr.update_metrics(e.code, e.added_on, bars)


def run_all() -> bool:
    ok = True
    for step in (step_quotes, step_qlib, step_tracklist):
        try:
            step()
        except Exception:                       # noqa: BLE001 — 单步失败不阻断
            ok = False
            traceback.print_exc()
    return ok


if __name__ == "__main__":
    sys.exit(0 if run_all() else 1)
```

- [ ] **Step 4: 运行,确认通过**

Run: `cd backend && .venv/bin/pytest tests/test_daily_full.py -v`
Expected: PASS(2 个)

- [ ] **Step 5: 提交**

```bash
git add backend/scripts/daily_full.py backend/tests/test_daily_full.py
git commit -m "feat(track): add daily_full orchestration (quotes->qlib->tracklist)"
```

---

## Task 6: APScheduler 调度器

**Files:**
- Modify: `backend/pyproject.toml`(加依赖)
- Modify: `backend/app/config.py`(加开关)
- Create: `backend/app/scheduler.py`
- Modify: `backend/app/main.py`(startup 启动)
- Test: `backend/tests/test_scheduler.py`

- [ ] **Step 1: 加依赖并安装**

修改 `backend/pyproject.toml` 的 `dependencies` 列表,在 `"pyqlib",` 后加一行:
```toml
  "apscheduler>=3.10",
```
安装:
```bash
cd backend && .venv/bin/pip install "apscheduler>=3.10"
```

- [ ] **Step 2: 加配置开关**

修改 `backend/app/config.py`,在 `Settings` 类内 `research_max_per_min` 之后加:
```python
    enable_scheduler: bool = False         # 默认关,生产/部署时置 True
    daily_update_hour: int = 16            # 北京时间 16:00
    daily_update_minute: int = 0
```

- [ ] **Step 3: 写失败测试**

```python
# backend/tests/test_scheduler.py
from app.scheduler import build_scheduler


def test_build_scheduler_registers_daily_job():
    calls = []
    sched = build_scheduler(lambda: calls.append("ran"), hour=16, minute=0)
    jobs = sched.get_jobs()
    assert len(jobs) == 1
    trig = str(jobs[0].trigger)
    assert "hour='16'" in trig and "minute='0'" in trig
    assert "Asia/Shanghai" in trig
    # 直接调用 job 函数验证回调可执行
    jobs[0].func()
    assert calls == ["ran"]
    sched.shutdown(wait=False)
```

- [ ] **Step 4: 运行,确认失败**

Run: `cd backend && .venv/bin/pytest tests/test_scheduler.py -v`
Expected: FAIL — `ModuleNotFoundError: app.scheduler`

- [ ] **Step 5: 实现调度器**

```python
# backend/app/scheduler.py
"""APScheduler 封装:每天指定的北京时间触发一个回调。"""
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger


def build_scheduler(job, hour: int = 16, minute: int = 0) -> BackgroundScheduler:
    sched = BackgroundScheduler(timezone="Asia/Shanghai")
    trigger = CronTrigger(hour=hour, minute=minute, timezone="Asia/Shanghai")
    sched.add_job(job, trigger, id="daily_full", replace_existing=True)
    return sched


def start_scheduler(job, hour: int = 16, minute: int = 0) -> BackgroundScheduler:
    sched = build_scheduler(job, hour=hour, minute=minute)
    sched.start()
    return sched
```

- [ ] **Step 6: 运行,确认通过**

Run: `cd backend && .venv/bin/pytest tests/test_scheduler.py -v`
Expected: PASS

- [ ] **Step 7: 在 startup 启动调度器(默认关闭,不影响测试)**

修改 `backend/app/main.py`:在 `create_app()` 内、`return app` 之前加:
```python
    settings = get_settings()
    if settings.enable_scheduler:
        from app.scheduler import start_scheduler
        from scripts.daily_full import run_all
        app.state.scheduler = start_scheduler(
            run_all, hour=settings.daily_update_hour,
            minute=settings.daily_update_minute)
```
并在 `main.py` 顶部已有 import 区加:
```python
from app.config import get_settings
```
(注意:`scripts` 需可导入;现有脚本均用 `sys.path.insert(parents[1])`,后端以 `backend/` 为工作目录运行 uvicorn 时 `scripts` 可直接 import。)

- [ ] **Step 8: 全量回归测试**

Run: `cd backend && .venv/bin/pytest -q`
Expected: 全绿(新老用例都过;调度器默认关闭,不会真触发)

- [ ] **Step 9: 提交**

```bash
git add backend/pyproject.toml backend/app/config.py backend/app/scheduler.py backend/app/main.py backend/tests/test_scheduler.py
git commit -m "feat(track): add APScheduler daily job at 16:00 Asia/Shanghai (off by default)"
```

---

## Task 7: 前端 apiDelete 辅助

**Files:**
- Modify: `frontend/src/api/client.ts`

- [ ] **Step 1: 追加 apiDelete**

在 `frontend/src/api/client.ts` 末尾追加:
```typescript
export async function apiDelete<T>(path: string): Promise<T> {
  const r = await fetch(`${BASE}${path}`, { method: "DELETE" });
  if (!r.ok) throw new Error(`DELETE ${path} failed: ${r.status}`);
  return r.json() as Promise<T>;
}
```

- [ ] **Step 2: 类型检查**

Run: `cd frontend && npm run build`
Expected: 构建通过(无类型错误)

- [ ] **Step 3: 提交**

```bash
git add frontend/src/api/client.ts
git commit -m "feat(track): add apiDelete client helper"
```

---

## Task 8: 跟踪表组件 TrackTable

**Files:**
- Create: `frontend/src/components/TrackTable.tsx`

- [ ] **Step 1: 实现组件**

```tsx
// frontend/src/components/TrackTable.tsx
import { Table, Empty, Button } from "antd";

export type Track = {
  code: string; name: string; added_on: string; entry_close: number;
  ret_t1: number | null; ret_t3: number | null;
  ret_t5: number | null; ret_t10: number | null;
  last_close: number | null; ret_since: number | null;
  max_gain: number | null; max_drawdown: number | null;
  last_updated: string | null;
};

const pct = (v: number | null) => (v == null ? "-" : `${(v * 100).toFixed(1)}%`);
const num = (v: number | null) => (v == null ? "-" : v.toFixed(2));

export function TrackTable(
  { rows, onRemove }: { rows: Track[]; onRemove: (code: string, on: string) => void },
) {
  if (!rows.length) return <Empty description="暂无跟踪标的" />;
  const columns = [
    { title: "代码", dataIndex: "code", key: "code" },
    { title: "名称", dataIndex: "name", key: "name" },
    { title: "入选日", dataIndex: "added_on", key: "d" },
    { title: "入选价", dataIndex: "entry_close", key: "ep", render: num },
    { title: "最新", dataIndex: "last_close", key: "lc", render: num },
    { title: "至今", dataIndex: "ret_since", key: "rs", render: pct },
    { title: "T+1", dataIndex: "ret_t1", key: "t1", render: pct },
    { title: "T+3", dataIndex: "ret_t3", key: "t3", render: pct },
    { title: "T+5", dataIndex: "ret_t5", key: "t5", render: pct },
    { title: "T+10", dataIndex: "ret_t10", key: "t10", render: pct },
    { title: "最大涨幅", dataIndex: "max_gain", key: "mg", render: pct },
    { title: "最大回撤", dataIndex: "max_drawdown", key: "md", render: pct },
    { title: "更新日", dataIndex: "last_updated", key: "u",
      render: (v: string | null) => v ?? "-" },
    { title: "操作", key: "op",
      render: (_: unknown, r: Track) => (
        <Button size="small" danger onClick={() => onRemove(r.code, r.added_on)}>
          删除
        </Button>
      ) },
  ];
  return <Table rowKey={(r) => `${r.code}-${r.added_on}`} size="small"
                pagination={false} dataSource={rows} columns={columns}
                scroll={{ x: true }} />;
}
```

- [ ] **Step 2: 类型检查**

Run: `cd frontend && npm run build`
Expected: 通过

- [ ] **Step 3: 提交**

```bash
git add frontend/src/components/TrackTable.tsx
git commit -m "feat(track): add TrackTable component"
```

---

## Task 9: 跟踪页 TrackPage + 路由/菜单

**Files:**
- Create: `frontend/src/pages/TrackPage.tsx`
- Create: `frontend/src/pages/TrackPage.test.tsx`
- Modify: `frontend/src/App.tsx`

- [ ] **Step 1: 写冒烟测试**

```tsx
// frontend/src/pages/TrackPage.test.tsx
import { render, screen } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { TrackPage } from "./TrackPage";

beforeEach(() => {
  vi.spyOn(globalThis, "fetch").mockResolvedValue(
    new Response(JSON.stringify([]), { status: 200 }) as unknown as Response,
  );
});

describe("TrackPage", () => {
  it("renders paste box and add button", async () => {
    render(<TrackPage />);
    expect(await screen.findByText("添加跟踪")).toBeTruthy();
    expect(screen.getByPlaceholderText(/粘贴/)).toBeTruthy();
  });
});
```

注:测试框架与现有 `ScreenerPool.test.tsx` 一致(vitest + @testing-library)。若现有测试用不同的 fetch mock 写法,沿用之。

- [ ] **Step 2: 运行,确认失败**

Run: `cd frontend && npx vitest run src/pages/TrackPage.test.tsx`
Expected: FAIL — 找不到 `./TrackPage`

- [ ] **Step 3: 实现页面**

```tsx
// frontend/src/pages/TrackPage.tsx
import { useEffect, useState } from "react";
import { Card, Input, Button, message, Space } from "antd";
import { apiGet, apiPost, apiDelete } from "../api/client";
import { TrackTable, type Track } from "../components/TrackTable";

export function TrackPage() {
  const [rows, setRows] = useState<Track[]>([]);
  const [text, setText] = useState("");
  const [loading, setLoading] = useState(false);

  const refresh = () =>
    apiGet<Track[]>("/api/track").then(setRows).catch(() => {});
  useEffect(() => { refresh(); }, []);

  const add = async () => {
    setLoading(true);
    try {
      const res = await apiPost<{ added: Track[] }>("/api/track", { text });
      message.success(`新增 ${res.added.length} 只`);
      setText("");
      await refresh();
    } catch {
      message.error("添加失败");
    } finally {
      setLoading(false);
    }
  };

  const remove = async (code: string, on: string) => {
    await apiDelete(`/api/track/${code}/${on}`).catch(() => {});
    await refresh();
  };

  return (
    <Space direction="vertical" style={{ width: "100%" }} size="middle">
      <Card title="添加跟踪(粘贴同花顺自选文本)">
        <Input.TextArea rows={6} value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="粘贴同花顺自选列表文本,自动识别 6 位代码" />
        <Button type="primary" loading={loading} onClick={add}
          style={{ marginTop: 12 }}>添加跟踪</Button>
      </Card>
      <Card title="我的跟踪(T+1/3/5/10 + 至今/最大涨幅/最大回撤)">
        <TrackTable rows={rows} onRemove={remove} />
      </Card>
    </Space>
  );
}
```

- [ ] **Step 4: 接入路由与菜单**

修改 `frontend/src/App.tsx`:
- import 区加:`import { TrackPage } from "./pages/TrackPage";`
- `ITEMS` 数组在 `{ key: "/screener", label: "选股池" },` 之后加:
  `{ key: "/track", label: "跟踪" },`
- `<Routes>` 内 `/screener` 那行之后加:
  `<Route path="/track" element={<TrackPage />} />`

- [ ] **Step 5: 运行测试 + 构建**

Run: `cd frontend && npx vitest run src/pages/TrackPage.test.tsx && npm run build`
Expected: 测试 PASS,构建通过

- [ ] **Step 6: 提交**

```bash
git add frontend/src/pages/TrackPage.tsx frontend/src/pages/TrackPage.test.tsx frontend/src/App.tsx
git commit -m "feat(track): add TrackPage with paste box, table, nav route"
```

---

## Task 10: 文档与开启说明

**Files:**
- Modify: `README.md`

- [ ] **Step 1: 在 README 增加"跟踪与定时更新"小节**

在 README 合适位置(脚本说明附近)追加:
```markdown
## 跟踪表 + 每日定时更新

- 前端「跟踪」页:粘贴同花顺自选文本即可加入跟踪,展示 T+1/3/5/10、至今涨跌、
  最大涨幅、最大回撤。
- 手动跑全套更新:`.venv/bin/python scripts/daily_full.py`
  (依次:全市场行情入库 → qlib 重建 → 跟踪表指标刷新)
- 自动调度:设置环境变量后由后端进程内置 APScheduler 每天 16:00(北京时间)触发。
  在 `.env` 中加:
  `ENABLE_SCHEDULER=true`(默认 false;需后端进程常驻)
  可选 `DAILY_UPDATE_HOUR=16` / `DAILY_UPDATE_MINUTE=0`
```

- [ ] **Step 2: 提交**

```bash
git add README.md
git commit -m "docs: document tracklist feature and daily scheduler"
```

---

## Self-Review 记录

- **Spec 覆盖**:跟踪表(T1)、解析器(T2)、Tracker A+B 指标(T3)、API add/list/delete(T4)、daily_full 行情/qlib/跟踪三步(T5)、APScheduler 16:00 Asia/Shanghai(T6)、前端页(T7-9)、错误处理(daily_full try/except、解析空返回、调度默认关)、测试(各 Task 均含)、文档(T10)。全部有对应任务。
- **占位符**:无 TBD/TODO;每个代码步骤含完整代码。
- **类型一致**:`Tracker.add(pairs, on, closes)`、`update_metrics(code, on, bars)`、`run_all()->bool`、`build_scheduler(job, hour, minute)`、前端 `Track` 类型字段与后端 `_row()` 输出键一一对应。
- **已知偏差**:指标用原始收盘价(与现有 WatchPool 一致),非 spec 的后复权——已在顶部 Note 标注。
