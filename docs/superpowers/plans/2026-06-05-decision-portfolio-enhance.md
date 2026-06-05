# 决策与持仓增强 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 决策页可输入代号触发异步 AI 辩论、决策默认自动批准并按最新收盘价执行、看板持仓显示买入时间/成本/盈亏、全站股票带名称。

**Architecture:** 后端新增 `stock_names` 表 + `NameLookup` 给响应附名称;扩展账户端点算持仓盈亏;`DecisionRunner` 接 broker 后落库即 APPROVED 并自动下单;新增 `decision_jobs` 表 + `POST /api/decisions/run`(setsid 后台子进程跑单只)+ `GET /api/decisions/jobs`。前端决策页加输入框/轮询/手动买卖面板,持仓与各列表显示名称与盈亏。

**Tech Stack:** FastAPI + SQLAlchemy + pytest;React + antd + vitest;tushare。

---

## 通用约定

- 后端在 `backend/`,用 `.venv/bin/python` / `.venv/bin/pytest`。前端在 `frontend/`,`npx vitest run`、`VITE_API_BASE="" npm run build`。
- 分支 `feat/decision-portfolio-enhance`(基于 feat/frontend-redesign),全部 commit 在此。每任务只 `git add` 本任务文件。
- 已有可复用:`normalize_code(code)`(`app/screener/tracklist_parser.py`,6位→ts_code);`build_brief(code, recent_closes, factors, fundamentals, holding, research=None)`;`PaperBroker(session).buy/sell(account_id, code, price, shares, on)` 抛 `InsufficientFunds/InsufficientShares`;`QuoteStore(session).get_bars(code, start, end)->[DailyBar(.close)]`;`ResponsiveList`(桌面表/手机卡,`forceMobile?` 钩子);`semanticColor(v)`(红涨绿跌);前端 `apiGet/apiPost`。

## 文件结构

- Modify `backend/app/db/models.py` — 加 `StockName`、`DecisionJob`
- Create `backend/app/data/names.py` — `NameLookup`
- Create `backend/app/data/prices.py` — `latest_close` helper
- Create `backend/scripts/sync_stock_names.py` — 拉 tushare 名称(含可测的 `sync_names`)
- Modify `backend/app/trading/schemas.py` — 扩展 `PositionOut`
- Modify `backend/app/api/routes_account.py` — 持仓盈亏
- Modify `backend/app/api/routes_discovery.py` / `routes_screener.py` — 附 name
- Modify `backend/app/decision/runner.py` — 自动批准+执行
- Modify `backend/app/api/routes_decisions.py` — name + run/jobs 端点
- Create `backend/scripts/run_one_decision.py` — 单只决策 worker
- Modify `backend/scripts/run_decisions.py` — 传 broker 走自动执行
- Frontend: `components/PositionsTable.tsx`、`components/ConclusionCard.tsx`、`pages/DecisionsPage.tsx`、各列表显示名称

---

### Task 1: StockName 模型 + NameLookup

**Files:**
- Modify: `backend/app/db/models.py`
- Create: `backend/app/data/names.py`
- Test: `backend/tests/test_names.py`

- [ ] **Step 1: 写测试** `backend/tests/test_names.py`:

```python
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.db.database import Base
import app.db.models  # noqa
from app.db.models import StockName
from app.data.names import NameLookup


def _sess():
    e = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                      poolclass=StaticPool, future=True)
    Base.metadata.create_all(e)
    return sessionmaker(bind=e, future=True)()


def test_lookup_map_and_get():
    s = _sess()
    s.add_all([StockName(code="600519.SH", name="贵州茅台"),
               StockName(code="300285.SZ", name="国瓷材料")])
    s.commit()
    nl = NameLookup(s)
    assert nl.get("600519.SH") == "贵州茅台"
    assert nl.get("000001.SZ") == ""          # 缺失回退空串
    assert nl.map(["600519.SH", "300285.SZ", "x"]) == {
        "600519.SH": "贵州茅台", "300285.SZ": "国瓷材料"}
    assert nl.map([]) == {}
```

- [ ] **Step 2: 跑,确认 FAIL** — `.venv/bin/pytest tests/test_names.py -v`

- [ ] **Step 3: 实现** — 在 `app/db/models.py` 末尾追加(确认文件顶部已 import `String`):

```python
class StockName(Base):
    __tablename__ = "stock_names"
    code: Mapped[str] = mapped_column(String(16), primary_key=True)
    name: Mapped[str] = mapped_column(String(32), default="")
```

`app/data/names.py`:

```python
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.db.models import StockName


class NameLookup:
    def __init__(self, session: Session):
        self.s = session

    def map(self, codes) -> dict[str, str]:
        codes = list({c for c in codes})
        if not codes:
            return {}
        rows = self.s.scalars(select(StockName).where(StockName.code.in_(codes))).all()
        return {r.code: r.name for r in rows}

    def get(self, code: str) -> str:
        r = self.s.get(StockName, code)
        return r.name if r else ""
```

- [ ] **Step 4: 跑,确认 PASS** — `.venv/bin/pytest tests/test_names.py -v`

- [ ] **Step 5: Commit**

```bash
git add app/db/models.py app/data/names.py tests/test_names.py
git commit -m "feat(data): StockName table + NameLookup"
```

---

### Task 2: sync_stock_names 脚本(tushare 名称)

**Files:**
- Create: `backend/scripts/sync_stock_names.py`
- Test: `backend/tests/test_sync_names.py`

把可测的纯函数 `sync_names(session, rows)` 与 tushare 拉取分离。

- [ ] **Step 1: 写测试** `backend/tests/test_sync_names.py`:

```python
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.db.database import Base
import app.db.models  # noqa
from app.db.models import StockName
from scripts.sync_stock_names import sync_names


def _sess():
    e = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                      poolclass=StaticPool, future=True)
    Base.metadata.create_all(e)
    return sessionmaker(bind=e, future=True)()


def test_sync_names_upserts_idempotently():
    s = _sess()
    sync_names(s, [("600519.SH", "贵州茅台"), ("300285.SZ", "国瓷材料")])
    assert s.get(StockName, "600519.SH").name == "贵州茅台"
    # 重跑 + 改名 → 幂等更新,不重复
    sync_names(s, [("600519.SH", "茅台"), ("000001.SZ", "平安银行")])
    assert s.get(StockName, "600519.SH").name == "茅台"
    assert s.get(StockName, "000001.SZ").name == "平安银行"
    assert s.query(StockName).count() == 3
```

- [ ] **Step 2: 跑,确认 FAIL** — `.venv/bin/pytest tests/test_sync_names.py -v`

- [ ] **Step 3: 实现** `backend/scripts/sync_stock_names.py`:

```python
"""拉 tushare stock_basic 全市场 code->name 落库(幂等)。用法:python scripts/sync_stock_names.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings
from app.db.database import make_engine, make_session_factory, Base
import app.db.models  # noqa: F401
from app.db.models import StockName


def sync_names(session, rows) -> int:
    for code, name in rows:
        existing = session.get(StockName, code)
        if existing:
            existing.name = name
        else:
            session.add(StockName(code=code, name=name))
    session.commit()
    return len(list(rows))


def fetch_rows(token: str):
    import tushare as ts
    pro = ts.pro_api(token)
    df = pro.stock_basic(exchange="", list_status="L", fields="ts_code,name")
    return [(r.ts_code, r.name) for r in df.itertuples(index=False)]


def main():
    s = get_settings()
    engine = make_engine(); Base.metadata.create_all(engine)
    session = make_session_factory(engine)()
    rows = fetch_rows(s.tushare_token)
    n = sync_names(session, rows)
    print(f"SYNC_NAMES_DONE n={n}", flush=True)


if __name__ == "__main__":
    main()
```

> 注:`get_settings()` 的 tushare token 字段名以 `app/config.py` 现有为准(可能是 `tushare_token`);若不同,用真实字段名。

- [ ] **Step 4: 跑,确认 PASS** — `.venv/bin/pytest tests/test_sync_names.py -v`

- [ ] **Step 5: Commit**

```bash
git add scripts/sync_stock_names.py tests/test_sync_names.py
git commit -m "feat(scripts): sync_stock_names from tushare stock_basic"
```

---

### Task 3: discovery/screener/decisions 列表附名称

**Files:**
- Modify: `backend/app/api/routes_discovery.py`
- Modify: `backend/app/api/routes_screener.py`
- Modify: `backend/app/api/routes_decisions.py`(仅 list_decisions 与 get_decision 加 name)
- Test: `backend/tests/test_api_names.py`

- [ ] **Step 1: 写测试** `backend/tests/test_api_names.py`(复用各文件已有的内存建库法;此处自建):

```python
from datetime import date
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.db.database import Base
import app.db.models  # noqa
from app.db.models import StockName, Decision
from app.main import create_app
from app.api.deps import get_session


def _client():
    e = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                      poolclass=StaticPool, future=True)
    Base.metadata.create_all(e)
    s = sessionmaker(bind=e, future=True)()
    s.add(StockName(code="600519.SH", name="贵州茅台"))
    s.add(Decision(as_of=date(2026, 6, 4), code="600519.SH", action="HOLD",
                   confidence=0.5, shares=0, reasoning="### 风控经理\n观望",
                   status="PENDING", created_at=date(2026, 6, 4)))
    s.commit()
    app = create_app()
    app.dependency_overrides[get_session] = lambda: s
    return TestClient(app), s


def test_decisions_list_has_name():
    client, _ = _client()
    data = client.get("/api/decisions").json()
    assert data[0]["name"] == "贵州茅台"


def test_decision_detail_has_name():
    client, _ = _client()
    rows = client.get("/api/decisions").json()
    d = client.get(f"/api/decisions/{rows[0]['id']}").json()
    assert d["name"] == "贵州茅台"
```

- [ ] **Step 2: 跑,确认 FAIL** — `.venv/bin/pytest tests/test_api_names.py -v`

- [ ] **Step 3: 实现** — 在三个路由用 `NameLookup` 给响应加 `name`:
  - `routes_decisions.py`:`from app.data.names import NameLookup`。`list_decisions` 内对结果 codes 批量 `NameLookup(s).map(codes)`,每条加 `"name": names.get(r.code, "")`。`get_decision` 把返回里的 `"name": None` 改为 `NameLookup(s).get(d.code)`。
  - `routes_discovery.py`:对返回列表加 `"name": names.get(r.code, "")`(同法批量)。
  - `routes_screener.py`:对返回列表加 `"name": names.get(p.code, "")`。

> 实现时 import `NameLookup`,在各函数取到 rows 后构建 `names = NameLookup(s).map([...codes...])`,字典 `.get(code, "")` 附名。

- [ ] **Step 4: 跑,确认 PASS** — `.venv/bin/pytest tests/test_api_names.py tests/test_api_decisions.py -v`(原决策测试仍需通过)

- [ ] **Step 5: Commit**

```bash
git add app/api/routes_discovery.py app/api/routes_screener.py app/api/routes_decisions.py tests/test_api_names.py
git commit -m "feat(api): attach stock name to discovery/screener/decisions responses"
```

---

### Task 4: 持仓盈亏(schema + account 端点)

**Files:**
- Create: `backend/app/data/prices.py`
- Modify: `backend/app/trading/schemas.py`
- Modify: `backend/app/api/routes_account.py`
- Test: `backend/tests/test_api_account_pnl.py`

- [ ] **Step 1: 写测试** `backend/tests/test_api_account_pnl.py`:

```python
from datetime import date
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.db.database import Base
import app.db.models  # noqa
from app.db.models import Account, Position, Trade, StockName, DailyQuote
from app.main import create_app
from app.api.deps import get_session


def _client():
    e = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                      poolclass=StaticPool, future=True)
    Base.metadata.create_all(e)
    s = sessionmaker(bind=e, future=True)()
    s.add(Account(id=1, name="main", cash=100000.0))
    s.add(Position(account_id=1, code="600519.SH", shares=100, cost=1500.0))
    s.add(StockName(code="600519.SH", name="贵州茅台"))
    s.add(Trade(account_id=1, code="600519.SH", side="BUY", price=1500.0,
                shares=100, traded_at=date(2026, 6, 1)))
    s.add(DailyQuote(code="600519.SH", trade_date=date(2026, 6, 4), open=1500,
                     high=1700, low=1490, close=1650.0, vol=1.0, amount=1.0))
    s.commit()
    app = create_app()
    app.dependency_overrides[get_session] = lambda: s
    return TestClient(app), s


def test_account_position_has_pnl_and_name_and_buydate():
    client, _ = _client()
    p = client.get("/api/account/1").json()["positions"][0]
    assert p["name"] == "贵州茅台"
    assert p["buy_date"] == "2026-06-01"
    assert p["last_close"] == 1650.0
    assert p["market_value"] == 1650.0 * 100
    assert round(p["pnl"], 2) == round((1650.0 - 1500.0) * 100, 2)
    assert round(p["pnl_pct"], 4) == round(1650.0 / 1500.0 - 1, 4)
```

> 注:`DailyQuote` 实际字段名以 `app/db/models.py` 为准(可能含 adj_factor 等必填项);构造时补齐 NOT NULL 字段。若 close 列名不同,改成真实列名。

- [ ] **Step 2: 跑,确认 FAIL** — `.venv/bin/pytest tests/test_api_account_pnl.py -v`

- [ ] **Step 3: 实现**
`app/data/prices.py`:

```python
from datetime import date
from app.data.quote_store import QuoteStore


def latest_close(store: QuoteStore, code: str, on: date) -> float | None:
    start = date(on.year - 1, on.month, on.day)
    bars = store.get_bars(code, start, on)
    return bars[-1].close if bars else None
```

`app/trading/schemas.py` — 扩展 `PositionOut`:

```python
class PositionOut(BaseModel):
    code: str
    name: str = ""
    shares: int
    cost: float
    buy_date: date | None = None
    last_close: float | None = None
    market_value: float | None = None
    pnl: float | None = None
    pnl_pct: float | None = None
```

`app/api/routes_account.py` — `get_account` 计算各字段:

```python
from datetime import date as date_t
from sqlalchemy import select, func
from app.data.names import NameLookup
from app.data.prices import latest_close
from app.data.quote_store import QuoteStore
from app.db.models import Trade

# ...在 get_account 内,取到 positions 后:
store = QuoteStore(s)
names = NameLookup(s)
today = date_t.today()
out = []
for p in positions:
    lc = latest_close(store, p.code, today)
    buy = s.scalar(select(func.min(Trade.traded_at)).where(
        Trade.account_id == account_id, Trade.code == p.code, Trade.side == "BUY"))
    mv = lc * p.shares if lc is not None else None
    pnl = (lc - p.cost) * p.shares if lc is not None else None
    pnl_pct = (lc / p.cost - 1) if (lc is not None and p.cost) else None
    out.append(PositionOut(code=p.code, name=names.get(p.code), shares=p.shares,
        cost=p.cost, buy_date=buy, last_close=lc, market_value=mv,
        pnl=pnl, pnl_pct=pnl_pct))
return AccountOut(id=acc.id, name=acc.name, cash=acc.cash, positions=out)
```

(`s` 是 session 依赖名;以现有签名为准 —— 现文件用 `s: Session = Depends(get_session)`。)

- [ ] **Step 4: 跑,确认 PASS** — `.venv/bin/pytest tests/test_api_account_pnl.py -v`

- [ ] **Step 5: Commit**

```bash
git add app/data/prices.py app/trading/schemas.py app/api/routes_account.py tests/test_api_account_pnl.py
git commit -m "feat(api): account positions return name/buy_date/last_close/pnl"
```

---

### Task 5: 看板持仓显示盈亏(前端)

**Files:**
- Modify: `frontend/src/components/PositionsTable.tsx`
- Test: `frontend/src/components/PositionsTable.test.tsx`(更新)

- [ ] **Step 1: 更新测试** — 在现有 `PositionsTable.test.tsx` 的 position 数据补字段并断言名称/盈亏显示:

```tsx
import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { PositionsTable } from "./PositionsTable";

const POS = [{ code: "600519.SH", name: "贵州茅台", shares: 100, cost: 1500,
  buy_date: "2026-06-01", last_close: 1650, market_value: 165000,
  pnl: 15000, pnl_pct: 0.1 }];

describe("PositionsTable", () => {
  it("mobile card shows name, buy date and pnl", () => {
    render(<PositionsTable positions={POS as any} forceMobile={true} />);
    expect(screen.getByText("贵州茅台")).toBeInTheDocument();
    expect(screen.getByText(/2026-06-01/)).toBeInTheDocument();
    expect(screen.getByText(/15000/)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: 跑,确认 FAIL** — `npx vitest run src/components/PositionsTable.test.tsx`

- [ ] **Step 3: 实现** — 扩展 `PositionsTable` 的类型与列/卡片:
  - Position 类型加 `name, buy_date, last_close, market_value, pnl, pnl_pct`(都可空)。
  - 桌面 columns 增列:名称、买入时间、现价、市值、盈亏(用 `semanticColor(pnl)` 上色,显示 `pnl`(`pnl_pct*100`%))。
  - renderCard 显示:`名称(代码)` + 股数/成本 + 买入时间 + 盈亏 Tag(`semanticColor(pnl)`,文本如 `+15000 (+10.0%)`)。
  - 数值为 null 时显示 `—`。

```tsx
// renderCard 关键片段
const pnlText = p.pnl == null ? "—"
  : `${p.pnl >= 0 ? "+" : ""}${p.pnl.toFixed(0)} (${(p.pnl_pct! * 100).toFixed(1)}%)`;
// ...
<Card size="small">
  <Space split="·"><b>{p.name || p.code}</b><span>{p.code}</span></Space>
  <div style={{ marginTop: 6 }}>
    <Tag>股数 {p.shares}</Tag><Tag>成本 {p.cost}</Tag>
    {p.buy_date && <Tag>买入 {p.buy_date}</Tag>}
    <Tag color={semanticColor(p.pnl)}>{pnlText}</Tag>
  </div>
</Card>
```

import `Tag, Space` from antd、`semanticColor` from "../theme/tokens"。

- [ ] **Step 4: 跑,确认 PASS** — `npx vitest run src/components/PositionsTable.test.tsx`;`npx tsc --noEmit` 干净。

- [ ] **Step 5: Commit**

```bash
git add src/components/PositionsTable.tsx src/components/PositionsTable.test.tsx
git commit -m "feat(frontend): positions show name/buy date/pnl"
```

---

### Task 6: 决策自动批准 + 执行(runner)

**Files:**
- Modify: `backend/app/decision/runner.py`
- Test: `backend/tests/test_decision_autoexec.py`

`DecisionRunner` 增加可选 `broker`、`account_id`、`price_of`;给了 broker 就落库 APPROVED 并自动下单;不给 → 维持 PENDING(向后兼容,旧测试不变)。

- [ ] **Step 1: 写测试** `backend/tests/test_decision_autoexec.py`:

```python
from datetime import date
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.db.database import Base
import app.db.models  # noqa
from app.db.models import Account
from app.decision.runner import DecisionRunner
from app.decision.brief import build_brief
from app.trading.broker import PaperBroker


class FakeGraphDecision:
    def __init__(self, action, shares):
        self.action = action
        self.confidence = 0.7
        self.shares = shares
        self.reasoning = "### 风控经理\n裁决"


class FakeGraph:
    def __init__(self, action, shares):
        self._a = action
        self._s = shares

    def run(self, brief):
        return FakeGraphDecision(self._a, self._s)


def _sess():
    e = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                      poolclass=StaticPool, future=True)
    Base.metadata.create_all(e)
    s = sessionmaker(bind=e, future=True)()
    s.add(Account(id=1, name="main", cash=1_000_000.0)); s.commit()
    return s


def test_autoexec_buy_sets_approved_and_buys():
    s = _sess()
    broker = PaperBroker(s)
    runner = DecisionRunner(s, FakeGraph("BUY", 100), broker=broker,
                            account_id=1, price_of=lambda c: 100.0)
    out = runner.run(date(2026, 6, 4), [build_brief("600519.SH", [100], {}, {}, None)])
    assert out[0].status == "APPROVED"
    acc = s.get(Account, 1)
    assert acc.cash == 1_000_000.0 - 100.0 * 100   # 已扣款建仓


def test_autoexec_hold_no_trade_but_approved():
    s = _sess()
    runner = DecisionRunner(s, FakeGraph("HOLD", 0), broker=PaperBroker(s),
                            account_id=1, price_of=lambda c: 100.0)
    out = runner.run(date(2026, 6, 4), [build_brief("X", [1], {}, {}, None)])
    assert out[0].status == "APPROVED"
    assert s.get(Account, 1).cash == 1_000_000.0


def test_no_broker_keeps_pending():
    s = _sess()
    runner = DecisionRunner(s, FakeGraph("BUY", 100))
    out = runner.run(date(2026, 6, 4), [build_brief("X", [1], {}, {}, None)])
    assert out[0].status == "PENDING"
```

- [ ] **Step 2: 跑,确认 FAIL** — `.venv/bin/pytest tests/test_decision_autoexec.py -v`

- [ ] **Step 3: 实现** — 改 `app/decision/runner.py`:

```python
from datetime import date
from typing import Callable, Optional
from sqlalchemy import delete
from sqlalchemy.orm import Session
from app.db.models import Decision
from app.decision.graph import DecisionGraph
from app.decision.brief import StockBrief
from app.trading.broker import PaperBroker, InsufficientFunds, InsufficientShares


class DecisionRunner:
    def __init__(self, session: Session, graph: DecisionGraph,
                 broker: Optional[PaperBroker] = None, account_id: int = 1,
                 price_of: Optional[Callable[[str], Optional[float]]] = None):
        self.s = session
        self.graph = graph
        self.broker = broker
        self.account_id = account_id
        self.price_of = price_of

    def run(self, as_of: date, briefs: list[StockBrief]) -> list[Decision]:
        out = []
        for brief in briefs:
            d = self.graph.run(brief)
            self.s.execute(delete(Decision).where(
                Decision.as_of == as_of, Decision.code == brief.code))
            status = "PENDING"
            reasoning = d.reasoning
            if self.broker is not None:
                status = "APPROVED"
                if d.action in ("BUY", "SELL") and d.shares > 0:
                    price = self.price_of(brief.code) if self.price_of else None
                    if price:
                        try:
                            if d.action == "BUY":
                                self.broker.buy(self.account_id, brief.code, price, d.shares, as_of)
                            else:
                                self.broker.sell(self.account_id, brief.code, price, d.shares, as_of)
                        except (InsufficientFunds, InsufficientShares) as e:
                            reasoning += f"\n\n⚠️ 自动执行失败:{e}"
                    else:
                        reasoning += "\n\n⚠️ 自动执行跳过:无最新价"
            row = Decision(as_of=as_of, code=brief.code, action=d.action,
                           confidence=d.confidence, shares=d.shares,
                           reasoning=reasoning, status=status, created_at=as_of)
            self.s.add(row); out.append(row)
        self.s.commit()
        return out
```

- [ ] **Step 4: 跑,确认 PASS** — `.venv/bin/pytest tests/test_decision_autoexec.py tests/test_decision_runner.py -v`(旧 runner 测试仍须过)

- [ ] **Step 5: Commit**

```bash
git add app/decision/runner.py tests/test_decision_autoexec.py
git commit -m "feat(decision): runner auto-approves and executes via broker when provided"
```

---

### Task 7: run_decisions 走自动执行 + 结论卡显示「已自动执行」

**Files:**
- Modify: `backend/scripts/run_decisions.py`
- Modify: `frontend/src/components/ConclusionCard.tsx`

- [ ] **Step 1: run_decisions.py** — 构造 runner 时传 broker 与 price_of。在 `from app.decision.runner import DecisionRunner` 后加 `from app.trading.broker import PaperBroker`、`from app.data.prices import latest_close`,把第 53 行改为:

```python
broker = PaperBroker(session)
runner = DecisionRunner(session, DecisionGraph(_llm(s), rounds=s.debate_rounds),
                        broker=broker, account_id=1,
                        price_of=lambda c: latest_close(store, c, as_of))
```

- [ ] **Step 2: ConclusionCard.tsx** — 当 `status === "APPROVED"`(或非 PENDING)时,不渲染批准/驳回按钮,改显示一行 `✅ 已自动执行(<action> @ 已结算)`;`status === "PENDING"` 时维持原批准/驳回。现有测试 `hides buttons when not PENDING` 仍成立。补一条断言可选:

```tsx
// 在 APPROVED 分支渲染:
{c.status !== "PENDING" && (
  <span style={{ color: "#13c281" }}>✅ 已自动执行({c.action})</span>
)}
```

放在原 PENDING 按钮块的 else 位置。运行 `npx vitest run src/components/ConclusionCard.test.tsx` 应仍通过。

- [ ] **Step 3: 验证** — 后端 `.venv/bin/pytest -q tests/test_decision_autoexec.py`;前端 `npx vitest run src/components/ConclusionCard.test.tsx`。

- [ ] **Step 4: Commit**

```bash
git add scripts/run_decisions.py frontend/src/components/ConclusionCard.tsx
git commit -m "feat: run_decisions auto-executes; ConclusionCard shows auto-executed state"
```

---

### Task 8: DecisionJob 模型 + run/jobs 端点

**Files:**
- Modify: `backend/app/db/models.py`(加 `DecisionJob`)
- Modify: `backend/app/api/routes_decisions.py`
- Test: `backend/tests/test_api_decision_jobs.py`

- [ ] **Step 1: 写测试** `backend/tests/test_api_decision_jobs.py`:

```python
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.db.database import Base
import app.db.models  # noqa
from app.db.models import DecisionJob
from app.main import create_app
from app.api.deps import get_session
import app.api.routes_decisions as rd


def _client(monkeypatch):
    e = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                      poolclass=StaticPool, future=True)
    Base.metadata.create_all(e)
    s = sessionmaker(bind=e, future=True)()
    app = create_app()
    app.dependency_overrides[get_session] = lambda: s
    monkeypatch.setattr(rd, "_spawn_decision_worker", lambda job_id, code: None)
    return TestClient(app), s


def test_run_creates_pending_job_and_normalizes(monkeypatch):
    client, s = _client(monkeypatch)
    r = client.post("/api/decisions/run", json={"code": "600519"})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "PENDING"
    assert body["code"] == "600519.SH"     # normalize 补后缀
    assert s.get(DecisionJob, body["id"]) is not None


def test_jobs_lists(monkeypatch):
    client, s = _client(monkeypatch)
    client.post("/api/decisions/run", json={"code": "600519"})
    jobs = client.get("/api/decisions/jobs").json()
    assert len(jobs) == 1 and jobs[0]["code"] == "600519.SH"
```

- [ ] **Step 2: 跑,确认 FAIL** — `.venv/bin/pytest tests/test_api_decision_jobs.py -v`

- [ ] **Step 3: 实现**
`app/db/models.py` 追加:

```python
class DecisionJob(Base):
    __tablename__ = "decision_jobs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(10), default="PENDING")  # PENDING/RUNNING/DONE/FAILED
    decision_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[date] = mapped_column(Date)
```

(确认 models.py 顶部已 import `Integer, String, Date, Mapped, mapped_column`、`date`。)

`app/api/routes_decisions.py` 追加(顶部加 imports):

```python
import os, sys, subprocess
from datetime import date as date_t
from pathlib import Path
from app.screener.tracklist_parser import normalize_code
from app.db.models import DecisionJob


class RunBody(BaseModel):
    code: str


def _spawn_decision_worker(job_id: int, code: str) -> None:
    root = Path(__file__).resolve().parents[2]   # backend/
    py = sys.executable
    script = root / "scripts" / "run_one_decision.py"
    subprocess.Popen(["setsid", py, str(script), "--code", code, "--job", str(job_id)],
                     cwd=str(root), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     start_new_session=True)


@router.post("/decisions/run")
def run_decision(body: RunBody, s: Session = Depends(get_session)):
    code = normalize_code(body.code)
    job = DecisionJob(code=code, status="PENDING", created_at=date_t.today())
    s.add(job); s.commit(); s.refresh(job)
    _spawn_decision_worker(job.id, code)
    return {"id": job.id, "code": job.code, "status": job.status}


@router.get("/decisions/jobs")
def list_jobs(s: Session = Depends(get_session)):
    rows = s.scalars(select(DecisionJob).order_by(DecisionJob.id.desc()).limit(20)).all()
    return [{"id": j.id, "code": j.code, "status": j.status,
             "decision_id": j.decision_id, "error": j.error} for j in rows]
```

> 路由顺序:把这两个端点放在 `get_decision`(`/decisions/{decision_id}`)**之前**,避免 `/decisions/run`、`/decisions/jobs` 被 `{decision_id}` 当作整型路径(FastAPI 对非整型会 422,但显式排前更稳)。

- [ ] **Step 4: 跑,确认 PASS** — `.venv/bin/pytest tests/test_api_decision_jobs.py tests/test_api_decisions.py tests/test_api_names.py -v`

- [ ] **Step 5: Commit**

```bash
git add app/db/models.py app/api/routes_decisions.py tests/test_api_decision_jobs.py
git commit -m "feat(api): DecisionJob model + POST /decisions/run + GET /decisions/jobs"
```

---

### Task 9: run_one_decision worker 脚本

**Files:**
- Create: `backend/scripts/run_one_decision.py`
- Test: `backend/tests/test_run_one_decision.py`

把可测的核心 `run_one(session, job_id, code, graph, store, research)` 与 CLI/LLM 装配分离。

- [ ] **Step 1: 写测试** `backend/tests/test_run_one_decision.py`:

```python
from datetime import date
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.db.database import Base
import app.db.models  # noqa
from app.db.models import Account, DecisionJob, DailyQuote
from app.data.quote_store import QuoteStore
from app.research.store import ResearchStore
from scripts.run_one_decision import run_one


class FakeDec:
    action="HOLD"; confidence=0.5; shares=0; reasoning="### 风控经理\n观望"
class FakeGraph:
    def run(self, brief): return FakeDec()


def _sess():
    e = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                      poolclass=StaticPool, future=True)
    Base.metadata.create_all(e)
    s = sessionmaker(bind=e, future=True)()
    s.add(Account(id=1, name="main", cash=100000.0))
    s.add(DailyQuote(code="600519.SH", trade_date=date(2026, 6, 4), open=1, high=1,
                     low=1, close=1650.0, vol=1.0, amount=1.0))
    j = DecisionJob(code="600519.SH", status="PENDING", created_at=date(2026, 6, 4))
    s.add(j); s.commit()
    return s, j.id


def test_run_one_marks_done_and_creates_decision():
    s, jid = _sess()
    run_one(s, jid, "600519.SH", FakeGraph(), QuoteStore(s), ResearchStore(s))
    job = s.get(DecisionJob, jid)
    assert job.status == "DONE"
    assert job.decision_id is not None
```

> `DailyQuote` 必填字段以模型为准,补齐。

- [ ] **Step 2: 跑,确认 FAIL** — `.venv/bin/pytest tests/test_run_one_decision.py -v`

- [ ] **Step 3: 实现** `backend/scripts/run_one_decision.py`:

```python
"""单只决策 worker。用法:python scripts/run_one_decision.py --code 600519.SH --job 3"""
import sys, argparse
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings
from app.db.database import make_engine, make_session_factory, Base
import app.db.models  # noqa: F401
from app.db.models import DecisionJob
from app.data.quote_store import QuoteStore
from app.data.prices import latest_close
from app.research.store import ResearchStore
from app.decision.llm import LocalClaudeClient, DeepSeekClient
from app.decision.brief import build_brief
from app.decision.graph import DecisionGraph
from app.decision.runner import DecisionRunner
from app.trading.broker import PaperBroker


def run_one(session, job_id, code, graph, store, research):
    job = session.get(DecisionJob, job_id)
    job.status = "RUNNING"; session.commit()
    try:
        as_of = store.trading_dates(date.today(), 1)[0]
        bars = store.get_bars(code, date(as_of.year - 1, as_of.month, as_of.day), as_of)
        closes = [b.close for b in bars][-20:]
        rnote = research.latest(code)
        r = ({"sentiment": rnote.sentiment, "rating_consensus": rnote.rating_consensus,
              "summary": rnote.summary} if rnote else None)
        brief = build_brief(code, closes, {}, {}, None, research=r)
        runner = DecisionRunner(session, graph, broker=PaperBroker(session),
                                account_id=1, price_of=lambda c: latest_close(store, c, as_of))
        out = runner.run(as_of, [brief])
        job.decision_id = out[0].id; job.status = "DONE"
    except Exception as e:  # noqa: BLE001
        job.status = "FAILED"; job.error = str(e)[:500]
    session.commit()


def _llm(s):
    if s.decision_llm == "deepseek":
        return DeepSeekClient(s.deepseek_api_key, s.deepseek_base_url, s.deepseek_model)
    return LocalClaudeClient(bin_path=s.claude_bin)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--code", required=True)
    ap.add_argument("--job", type=int, required=True)
    a = ap.parse_args()
    s = get_settings()
    engine = make_engine(); Base.metadata.create_all(engine)
    session = make_session_factory(engine)()
    run_one(session, a.job, a.code, DecisionGraph(_llm(s), rounds=s.debate_rounds),
            QuoteStore(session), ResearchStore(session))
    print(f"JOB_DONE job={a.job}", flush=True)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: 跑,确认 PASS** — `.venv/bin/pytest tests/test_run_one_decision.py -v`

- [ ] **Step 5: Commit**

```bash
git add scripts/run_one_decision.py tests/test_run_one_decision.py
git commit -m "feat(scripts): run_one_decision worker (job state machine + auto-exec)"
```

---

### Task 10: 决策页输入框 + jobs 轮询(前端)

**Files:**
- Modify: `frontend/src/pages/DecisionsPage.tsx`
- Test: `frontend/src/pages/DecisionsPage.test.tsx`(更新)

- [ ] **Step 1: 更新测试** — 给现有 DecisionsPage 测试加一条:输入代号点按钮触发 `POST /api/decisions/run`。沿用其现有 fetch stub 风格,扩展 stub 按 URL 分支返回 jobs/run:

```tsx
it("submitting a code calls /api/decisions/run", async () => {
  const calls: string[] = [];
  vi.stubGlobal("fetch", vi.fn((url: string, init?: any) => {
    calls.push(url + (init?.method ? `:${init.method}` : ""));
    if (/\/decisions\/jobs/.test(url)) return Promise.resolve({ ok: true, json: () => Promise.resolve([]) });
    if (/\/decisions\/run/.test(url)) return Promise.resolve({ ok: true, json: () => Promise.resolve({ id: 1, code: "600519.SH", status: "PENDING" }) });
    if (/\/decisions\/1$/.test(url)) return Promise.resolve({ ok: true, json: () => Promise.resolve({ id:1, code:"x", name:"", action:"HOLD", confidence:0, shares:0, status:"APPROVED", summary:"", roles:[] }) });
    return Promise.resolve({ ok: true, json: () => Promise.resolve([]) });
  }) as any);
  const { getByPlaceholderText, getByText } = render(<DecisionsPage />);
  fireEvent.change(getByPlaceholderText("输入股票代号"), { target: { value: "600519" } });
  fireEvent.click(getByText("开始辩论"));
  await waitFor(() => expect(calls.some((c) => /\/decisions\/run:POST/.test(c))).toBe(true));
});
```

(顶部 import 补 `fireEvent`、`waitFor`。)

- [ ] **Step 2: 跑,确认 FAIL** — `npx vitest run src/pages/DecisionsPage.test.tsx`

- [ ] **Step 3: 实现** — 在 `DecisionsPage` 顶部加输入区 + jobs 轮询:
  - state:`const [code, setCode] = useState("")`、`const [jobs, setJobs] = useState<Job[]>([])`。
  - `submit = async () => { if(!code.trim()) return; await apiPost("/api/decisions/run", { code: code.trim() }); setCode(""); loadJobs(); }`。
  - `loadJobs = () => apiGet<Job[]>("/api/decisions/jobs").then(setJobs).catch(()=>{})`;`useEffect` 挂载调一次 + `setInterval(loadJobs, 5000)`(清理)。
  - 顶部渲染:`<Space><Input placeholder="输入股票代号" value={code} onChange=.../><Button type="primary" onClick={submit}>开始辩论</Button></Space>`,下面列出进行中 jobs(code + status Tag)。
  - jobs 里出现新的 DONE 时刷新列表(简单起见:每次 loadJobs 后也 `loadList()`)。
  类型:`type Job = { id:number; code:string; status:string; decision_id:number|null }`。

- [ ] **Step 4: 跑,确认 PASS** — `npx vitest run src/pages/DecisionsPage.test.tsx`;`npx tsc --noEmit` 干净。

- [ ] **Step 5: Commit**

```bash
git add src/pages/DecisionsPage.tsx src/pages/DecisionsPage.test.tsx
git commit -m "feat(frontend): decision page code input + async job polling"
```

---

### Task 11: 决策详情页手动买/卖面板(前端)

**Files:**
- Create: `frontend/src/components/ManualTrade.tsx`
- Modify: `frontend/src/pages/DecisionsPage.tsx`(详情区底部挂载)
- Test: `frontend/src/components/ManualTrade.test.tsx`

- [ ] **Step 1: 写测试** `frontend/src/components/ManualTrade.test.tsx`:

```tsx
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { ManualTrade } from "./ManualTrade";

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn(() => Promise.resolve({ ok: true,
    json: () => Promise.resolve({}) })) as any);
});

describe("ManualTrade", () => {
  it("submits a BUY to /api/trade", async () => {
    const onDone = vi.fn();
    render(<ManualTrade code="600519.SH" onDone={onDone} />);
    fireEvent.click(screen.getByText("买入"));
    await waitFor(() => expect(onDone).toHaveBeenCalled());
  });
});
```

- [ ] **Step 2: 跑,确认 FAIL** — `npx vitest run src/components/ManualTrade.test.tsx`

- [ ] **Step 3: 实现** `frontend/src/components/ManualTrade.tsx`:

```tsx
import { useState } from "react";
import { Card, InputNumber, Button, Space, message } from "antd";
import { apiPost } from "../api/client";

export function ManualTrade({ code, onDone }: { code: string; onDone: () => void }) {
  const [price, setPrice] = useState(0);
  const [shares, setShares] = useState(100);
  const today = new Date().toISOString().slice(0, 10);
  async function trade(side: "BUY" | "SELL") {
    try {
      await apiPost("/api/trade", { account_id: 1, code, side, price, shares, on: today });
      message.success(`${side} ${code} 成功`);
      onDone();
    } catch { message.error("下单失败"); }
  }
  return (
    <Card size="small" title={`手动交易 ${code}`} style={{ marginTop: 16 }}>
      <Space wrap>
        <InputNumber addonBefore="价" value={price} onChange={(v) => setPrice(v ?? 0)} />
        <InputNumber addonBefore="股数" value={shares} onChange={(v) => setShares(v ?? 0)} />
        <Button danger onClick={() => trade("BUY")}>买入</Button>
        <Button onClick={() => trade("SELL")}>卖出</Button>
      </Space>
    </Card>
  );
}
```

> `new Date().toISOString()` 在前端运行时可用(此约束仅针对 Workflow 脚本环境,不影响浏览器/vitest)。

- [ ] **Step 4: 挂载** — 在 `DecisionsPage` 详情区(`ConclusionCard` + `RoleStages` 下面)加 `{detail && <ManualTrade code={detail.code} onDone={() => loadDetail(detail.id)} />}`(用账户刷新回调;若 DecisionsPage 无账户刷新就调 loadDetail/loadList)。import ManualTrade。

- [ ] **Step 5: 跑,确认 PASS** — `npx vitest run src/components/ManualTrade.test.tsx src/pages/DecisionsPage.test.tsx`;`npx tsc --noEmit` 干净。

- [ ] **Step 6: Commit**

```bash
git add src/components/ManualTrade.tsx src/components/ManualTrade.test.tsx src/pages/DecisionsPage.tsx
git commit -m "feat(frontend): manual buy/sell panel on decision detail"
```

---

### Task 12: 列表显示名称 + 全量验证 + 构建部署

**Files:**
- Modify: `frontend/src/pages/DecisionsPage.tsx`、`frontend/src/components/PicksTable.tsx`、`frontend/src/components/DiscoveryPanel.tsx`、`frontend/src/pages/ResearchPage.tsx`(各处把展示从 `code` 改为 `名称(代码)`,名称缺失只显代码)

- [ ] **Step 1: 前端各列表显示名称** — 这些响应现已带 `name` 字段(Task 3)。逐处:
  - DecisionsPage 列表列「代码」render + renderCard:`{r.name ? `${r.name}(${r.code})` : r.code}`(类型 ListItem 加 `name?: string`)。
  - PicksTable renderCard 与桌面列首列同样改;`Pick` 类型加 `name?`。
  - DiscoveryPanel 卡片/列首列同样改。
  - ResearchPage 列表卡片同样改;`Note` 类型加 `name?`。
  保持纯展示改动,不动数据流。

- [ ] **Step 2: 全量前端测试** — `npx vitest run`,全绿。若某测试因首列文本从纯 code 变 `名称(代码)` 而失败,用 `getByText(/600519\.SH/)` 正则或断言名称文本修正。

- [ ] **Step 3: 全量后端测试** — `cd backend && .venv/bin/pytest -q`,全绿。

- [ ] **Step 4: 构建** — `cd frontend && VITE_API_BASE="" npm run build`,exit 0。

- [ ] **Step 5: 同步股票名 + 重新部署** —
  - 一次性拉名称:`cd backend && setsid bash -c '.venv/bin/python scripts/sync_stock_names.py > /tmp/sync_names.log 2>&1' </dev/null &`,稍后看 `/tmp/sync_names.log` 出现 `SYNC_NAMES_DONE`。
  - `cd /root/caddy && ./caddy reload --config /root/caddy/Caddyfile`;curl `--resolve cd.makezhan.xyz:5173:127.0.0.1 https://cd.makezhan.xyz:5173/` 应 200。
  - 数据库需建新表(stock_names/decision_jobs):重启 uvicorn(create_app 会 `Base.metadata.create_all`)或跑一次 sync 脚本(其 main 会 create_all)。重启后端:`pkill -f 'uvicorn app.main'; cd backend && setsid bash -c '.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000 > /tmp/ashare_uvicorn.log 2>&1' </dev/null &`。

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/DecisionsPage.tsx frontend/src/components/PicksTable.tsx frontend/src/components/DiscoveryPanel.tsx frontend/src/pages/ResearchPage.tsx
git commit -m "feat(frontend): show 名称(代码) across lists; final wiring"
```

---

## 备注

- 自动批准会真实改动模拟账户(account_id=1),用最新收盘价成交;资金/持仓不足时决策仍 APPROVED 但 reasoning 追加 ⚠️ 提示,不抛错。
- 异步 worker 用 setsid 脱离(项目惯例);容器重启会让 RUNNING job 悬挂(spec 风险段已述,前端可只读展示,不自动重试)。
- 新表 `stock_names`/`decision_jobs` 靠 `Base.metadata.create_all`(create_app 与脚本 main 都会调)自动建。
- 名称同步是一次性/周期性操作,不进每日守护;需要刷新再手动跑 sync_stock_names.py。
