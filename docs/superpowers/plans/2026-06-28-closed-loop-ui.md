# 闭环 UI 同步 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 Phase 3 闭环数据(决策胜率、因子前向IC、策略动作、回撤)接进前端:新增两个 API 模块与三处扩展、两个新页(策略闸/归因)、Dashboard 健康面板、净值图叠加回撤、Decisions 增强。

**Architecture:** 后端按"一域一路由模块"加 `routes_attribution`/`routes_policy` 并扩展 `routes_account`(equity drawdown)与 `routes_decisions`(score);前端按现有页面模式(`apiGet`+`useEffect`+antd)加页与组件,图表复用 echarts(`EquityChart` 范本)。

**Tech Stack:** FastAPI + Pydantic + pytest TestClient(后端);React + TypeScript + Ant Design v6 + echarts + vitest/@testing-library(前端)。

## Global Constraints

- 后端不新增第三方依赖;路由模块用 `APIRouter(prefix="/api")` + `Depends(get_session)`,在 `app/main.py` `include_router` 注册。
- 后端测试用 `TestClient(create_app())` + `app.dependency_overrides[get_session] = lambda: s`,in-memory sqlite(StaticPool),沿用 `tests/test_api_*.py` 模式。
- 前端不新增第三方依赖(echarts/antd/react-router 已装);API 经 `apiGet<T>(path)`(`src/api/client.ts`),同源相对路径(不写 host:port)。
- 前端取数沿用 `useEffect(()=>{ apiGet(...).then(set).catch(()=>{}) }, [])` 静默失败。
- 前端测试沿用 vitest:`vi.stubGlobal('fetch', vi.fn(...))` mock 网络;涉及 echarts 的组件用 `vi.mock("echarts")` 避免 canvas。
- 不做实时推送、不做 e2e。
- 已核实:`/api/discovery` 已返回 `score`+`rank`(spec §4 该扩展无需新任务)。

---

### Task 1: 后端 routes_attribution(胜率 + 前向IC)

**Files:**
- Create: `backend/app/api/routes_attribution.py`
- Modify: `backend/app/main.py`(import + include_router)
- Test: `backend/tests/test_api_attribution.py`

**Interfaces:**
- Consumes: `app/attribution/outcomes.hit_rate(session, *, window, as_of)`、`app/db/models.{FactorICDaily, DecisionOutcome}`、`app/api/deps.get_session`。
- Produces:
  - `GET /api/attribution/hit-rate?window=30` → `{"window":int, "hit_rate":float|null, "n":int}`(as_of 取 DecisionOutcome 最大 decided_on,无则 date.today();n = 窗内 hit 非空数)
  - `GET /api/attribution/forward-ic?days=60` → `[{"as_of":str, "ic":float|null, "rank_ic":float|null, "n":int}]`(factor_ic_daily 最近 days 行,升序)

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_api_attribution.py
from datetime import date
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.db.database import Base
import app.db.models  # noqa
from app.db.models import DecisionOutcome, FactorICDaily
from app.main import create_app
from app.api.deps import get_session


def _client():
    engine = create_engine("sqlite:///:memory:", future=True,
                           connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, expire_on_commit=False, future=True)()
    s.add(DecisionOutcome(decision_id=1, code="600519.SH", decided_on=date(2026, 6, 4),
                          action="BUY", entry_close=100.0, ret_t5=0.05, hit=True,
                          last_updated=date(2026, 6, 12)))
    s.add(DecisionOutcome(decision_id=2, code="000001.SZ", decided_on=date(2026, 6, 4),
                          action="BUY", entry_close=50.0, ret_t5=-0.05, hit=False,
                          last_updated=date(2026, 6, 12)))
    s.add(FactorICDaily(as_of=date(2026, 6, 4), ic=0.02, rank_ic=0.07, n=4000))
    s.add(FactorICDaily(as_of=date(2026, 6, 5), ic=0.01, rank_ic=0.03, n=4100))
    s.commit()
    app = create_app()
    app.dependency_overrides[get_session] = lambda: s
    return TestClient(app)


def test_hit_rate():
    data = _client().get("/api/attribution/hit-rate?window=30").json()
    assert data["n"] == 2 and abs(data["hit_rate"] - 0.5) < 1e-9 and data["window"] == 30


def test_forward_ic_series():
    data = _client().get("/api/attribution/forward-ic?days=60").json()
    assert len(data) == 2
    assert data[0]["as_of"] == "2026-06-04" and data[1]["rank_ic"] == 0.03
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/pytest tests/test_api_attribution.py -v`
Expected: FAIL — 404 (route not registered) / ModuleNotFoundError

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/api/routes_attribution.py
from datetime import date as date_t
from fastapi import APIRouter, Depends
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from app.api.deps import get_session
from app.db.models import FactorICDaily, DecisionOutcome
from app.attribution.outcomes import hit_rate

router = APIRouter(prefix="/api", tags=["attribution"])


@router.get("/attribution/hit-rate")
def get_hit_rate(window: int = 30, s: Session = Depends(get_session)):
    as_of = s.scalar(select(func.max(DecisionOutcome.decided_on))) or date_t.today()
    start = as_of.fromordinal(as_of.toordinal() - window)
    n = s.scalar(select(func.count()).select_from(DecisionOutcome).where(
        DecisionOutcome.decided_on >= start, DecisionOutcome.decided_on <= as_of,
        DecisionOutcome.hit.is_not(None))) or 0
    return {"window": window, "hit_rate": hit_rate(s, window=window, as_of=as_of), "n": int(n)}


@router.get("/attribution/forward-ic")
def get_forward_ic(days: int = 60, s: Session = Depends(get_session)):
    rows = s.scalars(select(FactorICDaily).order_by(
        FactorICDaily.as_of.desc()).limit(days)).all()
    rows = sorted(rows, key=lambda r: r.as_of)
    return [{"as_of": r.as_of.isoformat(), "ic": r.ic, "rank_ic": r.rank_ic, "n": r.n}
            for r in rows]
```

Register in `backend/app/main.py`: add `routes_attribution` to the import tuple and `app.include_router(routes_attribution.router)` alongside the others.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/bin/pytest tests/test_api_attribution.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/routes_attribution.py backend/app/main.py backend/tests/test_api_attribution.py
git commit -m "feat(api): attribution endpoints (hit-rate + forward-ic series)"
```

---

### Task 2: 后端 routes_policy(策略动作审计)

**Files:**
- Create: `backend/app/api/routes_policy.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_api_policy.py`

**Interfaces:**
- Consumes: `app/db/models.PolicyAction`、`get_session`。
- Produces: `GET /api/policy/actions?limit=50` → `[{"id","kind","as_of","trigger","detail","status"}]`(按 as_of 倒序再 id 倒序)

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_api_policy.py
from datetime import date
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.db.database import Base
import app.db.models  # noqa
from app.db.models import PolicyAction
from app.main import create_app
from app.api.deps import get_session


def _client():
    engine = create_engine("sqlite:///:memory:", future=True,
                           connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, expire_on_commit=False, future=True)()
    s.add(PolicyAction(kind="RISK_OFF", as_of=date(2026, 6, 27), trigger='{"reason":"回撤"}',
                       detail="停买", status="AUTO", created_at=date(2026, 6, 27)))
    s.add(PolicyAction(kind="REMINE", as_of=date(2026, 6, 28), trigger='{"rolling_rank_ic":0.01}',
                       detail="重挖", status="AUTO", created_at=date(2026, 6, 28)))
    s.commit()
    app = create_app()
    app.dependency_overrides[get_session] = lambda: s
    return TestClient(app)


def test_policy_actions_desc():
    data = _client().get("/api/policy/actions?limit=50").json()
    assert len(data) == 2
    assert data[0]["kind"] == "REMINE"          # 最新在前
    assert data[1]["kind"] == "RISK_OFF" and data[1]["status"] == "AUTO"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/pytest tests/test_api_policy.py -v`
Expected: FAIL — 404

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/api/routes_policy.py
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.api.deps import get_session
from app.db.models import PolicyAction

router = APIRouter(prefix="/api", tags=["policy"])


@router.get("/policy/actions")
def policy_actions(limit: int = 50, s: Session = Depends(get_session)):
    rows = s.scalars(select(PolicyAction).order_by(
        PolicyAction.as_of.desc(), PolicyAction.id.desc()).limit(limit)).all()
    return [{"id": r.id, "kind": r.kind, "as_of": r.as_of.isoformat(),
             "trigger": r.trigger, "detail": r.detail, "status": r.status} for r in rows]
```

Register in `backend/app/main.py` (import + include_router).

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/bin/pytest tests/test_api_policy.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/routes_policy.py backend/app/main.py backend/tests/test_api_policy.py
git commit -m "feat(api): policy actions audit endpoint"
```

---

### Task 3: 扩展 equity(drawdown)+ decisions(score)

**Files:**
- Modify: `backend/app/trading/schemas.py`(EquityPoint 加 drawdown)
- Modify: `backend/app/api/routes_account.py`(get_equity 算逐点 drawdown)
- Modify: `backend/app/api/routes_decisions.py`(list_decisions 加 score)
- Test: `backend/tests/test_api_equity_drawdown.py`、`backend/tests/test_api_decisions_score.py`

**Interfaces:**
- Consumes: `EquitySnapshot`、`DiscoveryPick`、`Decision`。
- Produces:
  - `EquityPoint` 增字段 `drawdown: float`
  - `GET /api/equity/{id}` 每点 `drawdown` = total/累计peak − 1(升序逐点,peak 为到该点的历史最高 total)
  - `GET /api/decisions` 列表项加 `score: float|null`(关联同 as_of 同 code 的 DiscoveryPick.score)

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_api_equity_drawdown.py
from datetime import date
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.db.database import Base
import app.db.models  # noqa
from app.db.models import Account, EquitySnapshot
from app.main import create_app
from app.api.deps import get_session


def _client():
    engine = create_engine("sqlite:///:memory:", future=True,
                           connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, expire_on_commit=False, future=True)()
    s.add(Account(id=1, name="main", cash=0.0))
    for d, t in [(date(2026, 6, 1), 100.0), (date(2026, 6, 2), 120.0), (date(2026, 6, 3), 102.0)]:
        s.add(EquitySnapshot(account_id=1, as_of=d, cash=0, market_value=0, total=t))
    s.commit()
    app = create_app()
    app.dependency_overrides[get_session] = lambda: s
    return TestClient(app)


def test_equity_has_drawdown():
    data = _client().get("/api/equity/1").json()
    assert len(data) == 3
    assert data[0]["drawdown"] == 0.0              # 首点峰值=自身
    assert abs(data[2]["drawdown"] - (102/120 - 1)) < 1e-9   # 峰值120
```

```python
# backend/tests/test_api_decisions_score.py
from datetime import date
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.db.database import Base
import app.db.models  # noqa
from app.db.models import Account, Decision, DiscoveryPick
from app.main import create_app
from app.api.deps import get_session


def _client():
    engine = create_engine("sqlite:///:memory:", future=True,
                           connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, expire_on_commit=False, future=True)()
    s.add(Account(name="main", cash=0.0))
    d = date(2026, 6, 4)
    s.add(Decision(as_of=d, code="600519.SH", action="BUY", confidence=0.8, shares=100,
                   reasoning="x", status="APPROVED", created_at=d))
    s.add(DiscoveryPick(as_of=d, code="600519.SH", rank=1, score=0.95, factors="{}"))
    s.commit()
    app = create_app()
    app.dependency_overrides[get_session] = lambda: s
    return TestClient(app)


def test_decisions_include_score():
    data = _client().get("/api/decisions").json()
    assert data[0]["score"] == 0.95 and data[0]["confidence"] == 0.8
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && .venv/bin/pytest tests/test_api_equity_drawdown.py tests/test_api_decisions_score.py -v`
Expected: FAIL — KeyError 'drawdown' / 'score'

- [ ] **Step 3: Write minimal implementation**

In `backend/app/trading/schemas.py`, add to `EquityPoint`:
```python
class EquityPoint(BaseModel):
    as_of: date
    cash: float
    market_value: float
    total: float
    drawdown: float = 0.0
```

In `backend/app/api/routes_account.py` `get_equity`, compute peak/drawdown:
```python
@router.get("/equity/{account_id}", response_model=list[EquityPoint])
def get_equity(account_id: int, s: Session = Depends(get_session)):
    rows = s.scalars(
        select(EquitySnapshot).where(EquitySnapshot.account_id == account_id)
        .order_by(EquitySnapshot.as_of)
    ).all()
    out = []
    peak = None
    for r in rows:
        peak = r.total if peak is None else max(peak, r.total)
        dd = (r.total / peak - 1.0) if peak else 0.0
        out.append(EquityPoint(as_of=r.as_of, cash=r.cash, market_value=r.market_value,
                               total=r.total, drawdown=dd))
    return out
```

In `backend/app/api/routes_decisions.py` `list_decisions`, join DiscoveryPick scores for the target date. After `rows = ...`:
```python
    picks = {p.code: p.score for p in s.scalars(
        select(DiscoveryPick).where(DiscoveryPick.as_of == target)).all()}
    names = NameLookup(s).map([r.code for r in rows])
    return [{"id": r.id, "as_of": r.as_of.isoformat(), "code": r.code,
             "name": names.get(r.code, ""),
             "action": r.action, "confidence": r.confidence, "shares": r.shares,
             "status": r.status, "reasoning": r.reasoning,
             "score": picks.get(r.code)} for r in rows]
```
(Add `DiscoveryPick` to the `from app.db.models import ...` line in routes_decisions.py if not present.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && .venv/bin/pytest tests/test_api_equity_drawdown.py tests/test_api_decisions_score.py tests/test_api_decisions.py -v`
Expected: PASS(新测试 + 既有 decisions 测试无回归)

- [ ] **Step 5: Commit**

```bash
git add backend/app/trading/schemas.py backend/app/api/routes_account.py backend/app/api/routes_decisions.py backend/tests/test_api_equity_drawdown.py backend/tests/test_api_decisions_score.py
git commit -m "feat(api): equity drawdown per-point + decisions composite score"
```

---

### Task 4: 前端 归因页 + ForwardICChart

**Files:**
- Create: `frontend/src/components/ForwardICChart.tsx`
- Create: `frontend/src/pages/AttributionPage.tsx`
- Test: `frontend/src/pages/AttributionPage.test.tsx`

**Interfaces:**
- Consumes: `/api/attribution/hit-rate`、`/api/attribution/forward-ic`(Task 1)。
- Produces: `AttributionPage`(default-exported via named `export function AttributionPage`);`ForwardICChart({ points })`。

- [ ] **Step 1: Write the failing test**

```tsx
// frontend/src/pages/AttributionPage.test.tsx
import { render, screen } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { AttributionPage } from './AttributionPage'

vi.mock('echarts')   // 避免 canvas

beforeEach(() => {
  vi.stubGlobal('fetch', vi.fn((url: string) => {
    const body = url.includes('hit-rate')
      ? { window: 30, hit_rate: 0.6, n: 10 }
      : [{ as_of: '2026-06-04', ic: 0.02, rank_ic: 0.07, n: 4000 }]
    return Promise.resolve({ ok: true, json: () => Promise.resolve(body) }) as any
  }))
})

describe('AttributionPage', () => {
  it('renders hit-rate stat', async () => {
    render(<AttributionPage />)
    expect(await screen.findByText('归因')).toBeTruthy()
    expect(await screen.findByText(/胜率/)).toBeTruthy()
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/pages/AttributionPage.test.tsx`
Expected: FAIL — cannot find module AttributionPage

- [ ] **Step 3: Write minimal implementation**

```tsx
// frontend/src/components/ForwardICChart.tsx
import { useEffect, useRef } from "react";
import * as echarts from "echarts";

type Point = { as_of: string; ic: number | null; rank_ic: number | null; n: number };

export function ForwardICChart({ points }: { points: Point[] }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!ref.current) return;
    const chart = echarts.init(ref.current);
    chart.setOption({
      tooltip: { trigger: "axis" },
      legend: { data: ["IC", "RankIC"] },
      xAxis: { type: "category", data: points.map((p) => p.as_of) },
      yAxis: { type: "value", scale: true },
      series: [
        { name: "IC", type: "line", data: points.map((p) => p.ic), smooth: true },
        { name: "RankIC", type: "line", data: points.map((p) => p.rank_ic), smooth: true,
          markLine: { silent: true, data: [{ yAxis: 0.02 }] } },
      ],
    });
    return () => chart.dispose();
  }, [points]);
  return <div ref={ref} style={{ width: "100%", height: 300 }} />;
}
```

```tsx
// frontend/src/pages/AttributionPage.tsx
import { useEffect, useState } from "react";
import { Card, Statistic, Row, Col } from "antd";
import { apiGet } from "../api/client";
import { ForwardICChart } from "../components/ForwardICChart";

type HitRate = { window: number; hit_rate: number | null; n: number };
type ICPoint = { as_of: string; ic: number | null; rank_ic: number | null; n: number };

export function AttributionPage() {
  const [hr, setHr] = useState<HitRate | null>(null);
  const [ic, setIc] = useState<ICPoint[]>([]);
  useEffect(() => {
    apiGet<HitRate>("/api/attribution/hit-rate?window=30").then(setHr).catch(() => {});
    apiGet<ICPoint[]>("/api/attribution/forward-ic?days=60").then(setIc).catch(() => {});
  }, []);
  return (
    <div>
      <h2>归因</h2>
      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col xs={12}><Card><Statistic title="近30日胜率"
          value={hr?.hit_rate != null ? hr.hit_rate * 100 : NaN}
          precision={0} suffix="%" /></Card></Col>
        <Col xs={12}><Card><Statistic title="样本数" value={hr?.n ?? 0} /></Card></Col>
      </Row>
      <Card title="复合因子前向 IC / RankIC"><ForwardICChart points={ic} /></Card>
    </div>
  );
}
```

(Note: the page title is `<h2>归因</h2>`; the "胜率" text the test asserts comes from the Statistic title "近30日胜率".)

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/pages/AttributionPage.test.tsx`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/ForwardICChart.tsx frontend/src/pages/AttributionPage.tsx frontend/src/pages/AttributionPage.test.tsx
git commit -m "feat(ui): attribution page with forward-IC chart"
```

---

### Task 5: 前端 策略闸页 + 导航注册

**Files:**
- Create: `frontend/src/pages/PolicyPage.tsx`
- Test: `frontend/src/pages/PolicyPage.test.tsx`
- Modify: `frontend/src/components/SideNav.tsx`(NAV_MORE 加两项)
- Modify: `frontend/src/App.tsx`(两条 Route)

**Interfaces:**
- Consumes: `/api/policy/actions`(Task 2)。
- Produces: `PolicyPage`(named export)。

- [ ] **Step 1: Write the failing test**

```tsx
// frontend/src/pages/PolicyPage.test.tsx
import { render, screen } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { PolicyPage } from './PolicyPage'

beforeEach(() => {
  vi.stubGlobal('fetch', vi.fn(() => Promise.resolve({ ok: true,
    json: () => Promise.resolve([
      { id: 2, kind: 'REMINE', as_of: '2026-06-28', trigger: '{}', detail: '重挖', status: 'AUTO' },
      { id: 1, kind: 'RISK_OFF', as_of: '2026-06-27', trigger: '{}', detail: '停买', status: 'AUTO' },
    ]) }) as any))
})

describe('PolicyPage', () => {
  it('renders policy actions table', async () => {
    render(<PolicyPage />)
    expect(await screen.findByText('策略闸')).toBeTruthy()
    expect(await screen.findByText('重挖')).toBeTruthy()
    expect(await screen.findByText('停买')).toBeTruthy()
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/pages/PolicyPage.test.tsx`
Expected: FAIL — cannot find module PolicyPage

- [ ] **Step 3: Write minimal implementation**

```tsx
// frontend/src/pages/PolicyPage.tsx
import { useEffect, useState } from "react";
import { Card, Table, Tag } from "antd";
import { apiGet } from "../api/client";

type Action = { id: number; kind: string; as_of: string; trigger: string;
                detail: string; status: string };

const KIND_COLOR: Record<string, string> = {
  REMINE: "blue", RISK_OFF: "orange", WEAK_SELL: "red",
};
const STATUS_COLOR: Record<string, string> = {
  AUTO: "green", PENDING: "default", FAILED: "red",
};

export function PolicyPage() {
  const [rows, setRows] = useState<Action[]>([]);
  useEffect(() => {
    apiGet<Action[]>("/api/policy/actions?limit=50").then(setRows).catch(() => {});
  }, []);
  const columns = [
    { title: "时间", dataIndex: "as_of", key: "as_of" },
    { title: "类型", dataIndex: "kind", key: "kind",
      render: (k: string) => <Tag color={KIND_COLOR[k] || "default"}>{k}</Tag> },
    { title: "触发", dataIndex: "trigger", key: "trigger" },
    { title: "说明", dataIndex: "detail", key: "detail" },
    { title: "状态", dataIndex: "status", key: "status",
      render: (st: string) => <Tag color={STATUS_COLOR[st] || "default"}>{st}</Tag> },
  ];
  return (
    <div>
      <h2>策略闸</h2>
      <Card>
        <Table rowKey="id" dataSource={rows} columns={columns} size="small"
          locale={{ emptyText: "暂无策略动作" }} pagination={false} />
      </Card>
    </div>
  );
}
```

In `frontend/src/components/SideNav.tsx`, import two icons and add to `NAV_MORE`:
```tsx
import {
  DashboardOutlined, FundOutlined, EyeOutlined, RobotOutlined,
  FileTextOutlined, LineChartOutlined, SafetyOutlined, FundProjectionScreenOutlined,
} from "@ant-design/icons";
// ...
export const NAV_MORE = [
  { key: "/research", label: "研报", icon: <FileTextOutlined /> },
  { key: "/backtest", label: "回测", icon: <LineChartOutlined /> },
  { key: "/policy", label: "策略闸", icon: <SafetyOutlined /> },
  { key: "/attribution", label: "归因", icon: <FundProjectionScreenOutlined /> },
];
```

In `frontend/src/App.tsx`, import the two pages and add routes inside `<Routes>`:
```tsx
import { PolicyPage } from "./pages/PolicyPage";
import { AttributionPage } from "./pages/AttributionPage";
// inside <Routes>:
      <Route path="/policy" element={<PolicyPage />} />
      <Route path="/attribution" element={<AttributionPage />} />
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/pages/PolicyPage.test.tsx`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/PolicyPage.tsx frontend/src/pages/PolicyPage.test.tsx frontend/src/components/SideNav.tsx frontend/src/App.tsx
git commit -m "feat(ui): policy page + nav/route registration"
```

---

### Task 6: Dashboard 健康面板

**Files:**
- Create: `frontend/src/components/HealthPanel.tsx`
- Modify: `frontend/src/pages/Dashboard.tsx`(插入 HealthPanel)
- Test: `frontend/src/components/HealthPanel.test.tsx`

**Interfaces:**
- Consumes: `/api/attribution/hit-rate`、`/api/attribution/forward-ic`、`/api/policy/actions`、`/api/equity/{id}`。
- Produces: `HealthPanel({ accountId })`。

- [ ] **Step 1: Write the failing test**

```tsx
// frontend/src/components/HealthPanel.test.tsx
import { render, screen } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { HealthPanel } from './HealthPanel'

beforeEach(() => {
  vi.stubGlobal('fetch', vi.fn((url: string) => {
    let body: any = []
    if (url.includes('hit-rate')) body = { window: 30, hit_rate: 0.55, n: 8 }
    else if (url.includes('forward-ic')) body = [{ as_of: '2026-06-28', ic: 0.01, rank_ic: 0.05, n: 4000 }]
    else if (url.includes('policy/actions')) body = [{ id: 1, kind: 'RISK_OFF', as_of: '2026-06-28', trigger: '{}', detail: '停买', status: 'AUTO' }]
    else if (url.includes('equity')) body = [{ as_of: '2026-06-28', cash: 0, market_value: 0, total: 100, drawdown: -0.05 }]
    return Promise.resolve({ ok: true, json: () => Promise.resolve(body) }) as any
  }))
})

describe('HealthPanel', () => {
  it('renders the four health stats', async () => {
    render(<HealthPanel accountId={1} />)
    expect(await screen.findByText('近30日胜率')).toBeTruthy()
    expect(await screen.findByText('滚动RankIC')).toBeTruthy()
    expect(await screen.findByText('当前回撤')).toBeTruthy()
    expect(await screen.findByText('今日策略动作')).toBeTruthy()
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/components/HealthPanel.test.tsx`
Expected: FAIL — cannot find module HealthPanel

- [ ] **Step 3: Write minimal implementation**

```tsx
// frontend/src/components/HealthPanel.tsx
import { useEffect, useState } from "react";
import { Card, Statistic, Row, Col } from "antd";
import { useNavigate } from "react-router-dom";
import { apiGet } from "../api/client";

type HitRate = { window: number; hit_rate: number | null; n: number };
type ICPoint = { rank_ic: number | null };
type Action = { kind: string; as_of: string; detail: string };
type Eq = { drawdown: number };

export function HealthPanel({ accountId }: { accountId: number }) {
  const [hr, setHr] = useState<HitRate | null>(null);
  const [ric, setRic] = useState<number | null>(null);
  const [dd, setDd] = useState<number | null>(null);
  const [actions, setActions] = useState<Action[]>([]);
  const nav = useNavigate();
  useEffect(() => {
    apiGet<HitRate>("/api/attribution/hit-rate?window=30").then(setHr).catch(() => {});
    apiGet<ICPoint[]>("/api/attribution/forward-ic?days=60")
      .then((s) => setRic(s.length ? s[s.length - 1].rank_ic : null)).catch(() => {});
    apiGet<Eq[]>(`/api/equity/${accountId}`)
      .then((e) => setDd(e.length ? e[e.length - 1].drawdown : null)).catch(() => {});
    apiGet<Action[]>("/api/policy/actions?limit=50").then(setActions).catch(() => {});
  }, [accountId]);
  const today = actions[0]?.as_of;
  const todayCount = actions.filter((a) => a.as_of === today).length;
  const ddRed = dd != null && dd < -0.2;
  const hrRed = hr?.hit_rate != null && hr.hit_rate < 0.4;
  return (
    <Card title="闭环健康" style={{ marginBottom: 16 }}>
      <Row gutter={16}>
        <Col xs={12} sm={6}><Statistic title="近30日胜率"
          value={hr?.hit_rate != null ? hr.hit_rate * 100 : NaN} precision={0} suffix="%"
          valueStyle={hrRed ? { color: "#cf1322" } : undefined} /></Col>
        <Col xs={12} sm={6}><Statistic title="滚动RankIC"
          value={ric != null ? ric : NaN} precision={4} /></Col>
        <Col xs={12} sm={6}><Statistic title="当前回撤"
          value={dd != null ? dd * 100 : NaN} precision={1} suffix="%"
          valueStyle={ddRed ? { color: "#cf1322" } : undefined} /></Col>
        <Col xs={12} sm={6}><Statistic title="今日策略动作" value={todayCount} /></Col>
      </Row>
      {actions[0] && (
        <div style={{ marginTop: 8, cursor: "pointer", color: "#1677ff" }}
          onClick={() => nav("/policy")}>
          最近:{actions[0].as_of} {actions[0].kind} — {actions[0].detail}
        </div>
      )}
    </Card>
  );
}
```

In `frontend/src/pages/Dashboard.tsx`, import `HealthPanel` and render it above the 净值曲线 Card (use the existing `ACCOUNT_ID` constant):
```tsx
import { HealthPanel } from "../components/HealthPanel";
// ... in the returned JSX, before <Card title="净值曲线">:
      <HealthPanel accountId={ACCOUNT_ID} />
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/components/HealthPanel.test.tsx`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/HealthPanel.tsx frontend/src/pages/Dashboard.tsx frontend/src/components/HealthPanel.test.tsx
git commit -m "feat(ui): dashboard closed-loop health panel"
```

---

### Task 7: 净值图叠加回撤

**Files:**
- Modify: `frontend/src/components/EquityChart.tsx`
- Test: `frontend/src/components/EquityChart.test.tsx`

**Interfaces:**
- Consumes: `/api/equity/{id}` 的 `drawdown` 字段(Task 3)。
- Produces: `EquityChart({ points })` 支持可选 `drawdown` 字段,缺省只画净值线。

- [ ] **Step 1: Write the failing test**

```tsx
// frontend/src/components/EquityChart.test.tsx
import { render } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'
import { EquityChart } from './EquityChart'

const setOption = vi.fn()
vi.mock('echarts', () => ({
  init: () => ({ setOption, dispose: vi.fn() }),
}))

describe('EquityChart', () => {
  it('renders without drawdown field (backward compatible)', () => {
    setOption.mockClear()
    render(<EquityChart points={[{ as_of: '2026-06-01', total: 100 }]} />)
    expect(setOption).toHaveBeenCalled()   // 不崩,且不要求 drawdown
  })

  it('adds a drawdown series when drawdown present', () => {
    setOption.mockClear()
    render(<EquityChart points={[{ as_of: '2026-06-01', total: 100, drawdown: -0.05 }]} />)
    const opt = setOption.mock.calls[0][0]
    expect(opt.series.length).toBe(2)      // 净值 + 回撤两条
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/components/EquityChart.test.tsx`
Expected: FAIL — only 1 series / type error on drawdown

- [ ] **Step 3: Write minimal implementation**

Replace `frontend/src/components/EquityChart.tsx`:
```tsx
import { useEffect, useRef } from "react";
import * as echarts from "echarts";

type Point = { as_of: string; total: number; drawdown?: number };

export function EquityChart({ points }: { points: Point[] }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!ref.current) return;
    const chart = echarts.init(ref.current);
    const hasDd = points.some((p) => p.drawdown != null);
    const series: any[] = [
      { name: "净值", type: "line", data: points.map((p) => p.total), smooth: true },
    ];
    if (hasDd) {
      series.push({ name: "回撤", type: "line", yAxisIndex: 1, areaStyle: {},
        data: points.map((p) => (p.drawdown != null ? p.drawdown * 100 : null)), smooth: true });
    }
    chart.setOption({
      tooltip: { trigger: "axis" },
      xAxis: { type: "category", data: points.map((p) => p.as_of) },
      yAxis: hasDd
        ? [{ type: "value", scale: true }, { type: "value", name: "回撤%", max: 0 }]
        : { type: "value", scale: true },
      series,
    });
    return () => chart.dispose();
  }, [points]);
  return <div ref={ref} style={{ width: "100%", height: 300 }} />;
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/components/EquityChart.test.tsx`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/EquityChart.tsx frontend/src/components/EquityChart.test.tsx
git commit -m "feat(ui): equity chart drawdown overlay (backward compatible)"
```

---

### Task 8: Decisions 页增强(复合分列 + LOW_CONF 标)

**Files:**
- Modify: `frontend/src/pages/DecisionsPage.tsx`
- Test: `frontend/src/pages/DecisionsPage.test.tsx`(扩展)

**Interfaces:**
- Consumes: `/api/decisions` 列表项的 `score`、`confidence`、`status`(Task 3 + 现有)。
- Produces: DecisionsPage 表格新增 复合分/置信度 列,LOW_CONF 灰 Tag。

- [ ] **Step 1: Write the failing test**

Add to `frontend/src/pages/DecisionsPage.test.tsx` a case asserting the score column + LOW_CONF tag. First READ the existing test file to match its mock/setup style; then add:
```tsx
  it('shows composite score and LOW_CONF status', async () => {
    vi.stubGlobal('fetch', vi.fn((url: string) => {
      const body = url.includes('/api/decisions') && !url.match(/decisions\/\d/)
        ? [{ id: 1, code: '600519.SH', name: '贵州茅台', action: 'BUY',
             confidence: 0.5, status: 'LOW_CONF', score: 0.95, reasoning: '' }]
        : url.includes('jobs') ? [] : {}
      return Promise.resolve({ ok: true, json: () => Promise.resolve(body) }) as any
    }))
    render(<DecisionsPage />)
    expect(await screen.findByText('LOW_CONF')).toBeTruthy()
    expect(await screen.findByText('0.95')).toBeTruthy()
  })
```
(Match the existing file's imports/`describe` block — add this `it` inside it. Adjust the jobs/list URL discrimination to whatever the existing component fetches.)

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/pages/DecisionsPage.test.tsx`
Expected: FAIL — no "0.95" / score column

- [ ] **Step 3: Write minimal implementation**

In `frontend/src/pages/DecisionsPage.tsx`: extend the `ListItem` type with `confidence?: number; score?: number | null`, add two columns and a status renderer. Read the existing columns array and add:
```tsx
    { title: "复合分", dataIndex: "score", key: "score",
      render: (v: number | null | undefined) => (v == null ? "—" : v.toFixed(2)) },
    { title: "置信度", dataIndex: "confidence", key: "confidence",
      render: (v: number | undefined) => (v == null ? "—" : `${Math.round(v * 100)}%`) },
```
And change the 状态 column to color LOW_CONF grey:
```tsx
    { title: "状态", dataIndex: "status", key: "status",
      render: (st: string) => {
        const color = st === "APPROVED" ? "green" : st === "REJECTED" ? "red"
          : st === "LOW_CONF" ? "default" : undefined;
        return <Tag color={color}>{st}</Tag>;
      } },
```
(Ensure `Tag` is imported from antd in DecisionsPage.tsx — it already is for the action column. Update the `ListItem` type so `score`/`confidence` are recognized.)

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/pages/DecisionsPage.test.tsx`
Expected: PASS(新用例 + 既有用例)

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/DecisionsPage.tsx frontend/src/pages/DecisionsPage.test.tsx
git commit -m "feat(ui): decisions page composite score column + LOW_CONF tag"
```

---

## Self-Review

**Spec coverage(对照 spec):**
- §4 routes_attribution(hit-rate/forward-ic)→ Task 1 ✓
- §4 routes_policy(actions)→ Task 2 ✓
- §4 equity drawdown + decisions score → Task 3 ✓(discovery score/rank 已自带,无需任务,已在 Global Constraints 注明)
- §5 归因页 + ForwardICChart → Task 4 ✓
- §5 策略闸页 + 导航 → Task 5 ✓
- §6 Dashboard 健康面板 → Task 6 ✓
- §6 净值图叠加回撤 → Task 7 ✓
- §7 Decisions 增强(复合分/置信度/LOW_CONF)→ Task 8 ✓
- §7 弱因子标记走 reasoning 文本:Task 8 列表已返回 reasoning;详情抽屉的"弱因子"红标属增量,列表层 LOW_CONF + score 已满足"被策略闸盯上的可辨识性"。**有意缩减**:详情抽屉弱因子红标留待后续(spec §7 把它列为详情增量,非列表核心),不阻塞。
- §8 测试 → 每个任务含后端 pytest / 前端 vitest ✓

**Placeholder scan:** 无 TBD/TODO/占位代码(已移除 AttributionPage 里多余的隐藏 Card,标题为 `<h2>归因</h2>`)。每代码步含完整代码与预期命令输出。

**Type consistency:**
- `EquityPoint` 加 `drawdown`(Task 3)→ Task 7 EquityChart 的 Point 可选 `drawdown` 一致;Task 6 HealthPanel 读 `e[...].drawdown` 一致。
- `/api/attribution/hit-rate` 返回 `{window,hit_rate,n}`(Task 1)→ Task 4/6 前端类型 `HitRate` 一致。
- `/api/attribution/forward-ic` 返回 `[{as_of,ic,rank_ic,n}]`(Task 1)→ Task 4 ForwardICChart Point / Task 6 ICPoint 一致。
- `/api/policy/actions` 返回 `[{id,kind,as_of,trigger,detail,status}]`(Task 2)→ Task 5 PolicyPage / Task 6 Action 一致。
- `/api/decisions` 加 `score`(Task 3)→ Task 8 ListItem.score 一致。

**执行前需核对(给实现者):**
1. Task 1 `as_of.fromordinal(as_of.toordinal()-window)` 是按"自然日"回溯 window 天的简易写法;与 `hit_rate()` 内部 `as_of - timedelta(days=window)` 同义(都按自然日),用于算 n 与 hit_rate 的窗口一致即可。
2. Task 4 AttributionPage:测试断言的 `归因` 文案来自 `<h2>`、`胜率` 来自 Statistic title "近30日胜率"。
3. Task 8:先读 `DecisionsPage.tsx` 与其 `.test.tsx` 现状,新增列/用例要嵌进现有结构,URL 区分(列表 vs jobs vs 详情)按组件真实请求路径调整。
4. 前端运行测试命令:仓库若用 `npm test`/`vitest`,以 `cd frontend && npx vitest run <file>` 为准;若 `npx` 不可用,用 `npm run test -- run <file>`。
