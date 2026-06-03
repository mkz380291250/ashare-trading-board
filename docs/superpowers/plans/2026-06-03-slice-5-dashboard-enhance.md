# 切片5(看板增强) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用 Ant Design + react-router 重构看板,补齐研报/回测展示页,并新增回测结果落库与 API。

**Architecture:** 后端先行(pytest TDD):BacktestRun 落库 + `/api/backtest`、研报列表 `/api/research`。前端引入 antd + react-router + vitest,Layout/Menu 四页(看板/选股池/研报/回测),组件 antd 化,新增研报页与回测页。

**Tech Stack:** 后端 Python/FastAPI/SQLAlchemy/pytest。前端 React 19 + Vite + ECharts,新增 antd / react-router-dom / vitest + @testing-library/react + jsdom。

后端工作目录 `backend/`,测试 `.venv/bin/python -m pytest`。前端工作目录 `frontend/`,测试 `npm run test`、构建 `npm run build`。分支 `slice-5-dashboard`(已建,基于 main)。

已确认事实:
- `app/research/store.py`:`ResearchStore(session)` 有 `latest(code)`、`upsert(code, as_of, AnalyzedNote, source)`;`AnalyzedNote(sentiment, rating_consensus, summary)`。ORM `ResearchNote`(code, as_of, sentiment, rating_consensus, summary, source)。
- `app/backtest/strategy.py::summarize_report` 返回 `{days, cum_return, annualized_return, information_ratio, max_drawdown}`;`app/backtest/factor.py::factor_report` 返回 `{days, ic_mean, ic_ir, rank_ic_mean, rank_ic_ir, layer_returns}`。
- API 模式:`from app.api.deps import get_session`,router `prefix="/api"`,测试用 `create_app()` + `app.dependency_overrides[get_session]=lambda:s` + StaticPool(见 `tests/test_api_discovery.py`)。
- 前端 `api/client.ts` 有 `apiGet<T>(path)` / `apiPost<T>(path, body)`。`main.tsx` 渲染 `<App/>`。`build` = `tsc -b && vite build`。
- 现有组件:`PositionsTable`、`EquityChart`(ECharts)、`TradeForm`、`DiscoveryPanel`、`DecisionsPanel`、`PicksTable`;页面 `Dashboard`、`ScreenerPool`。

---

### Task 0: BacktestRun 模型 + BacktestStore

**Files:**
- Modify: `app/db/models.py`(末尾追加)
- Create: `app/backtest/store.py`
- Test: `tests/test_backtest_store.py`(新建)

- [ ] **Step 1: 写失败测试** — 新建 `tests/test_backtest_store.py`:

```python
from datetime import date
from app.backtest.store import BacktestStore


def test_save_and_latest(session):
    st = BacktestStore(session)
    st.save(signal="momentum", start=date(2026, 1, 2), end=date(2026, 6, 1),
            params={"topk": 8}, strategy_metrics={"annualized_return": 0.15},
            factor_report={"ic_mean": 0.07}, created_at=date(2026, 6, 3))
    run = st.latest()
    assert run.signal == "momentum"
    assert run.strategy_metrics_dict()["annualized_return"] == 0.15
    assert run.factor_report_dict()["ic_mean"] == 0.07
    assert run.params_dict()["topk"] == 8


def test_latest_none_when_empty(session):
    assert BacktestStore(session).latest() is None


def test_list_recent_orders_newest_first(session):
    st = BacktestStore(session)
    st.save(signal="a", start=date(2026, 1, 1), end=date(2026, 2, 1),
            params={}, strategy_metrics={}, factor_report={}, created_at=date(2026, 6, 1))
    st.save(signal="b", start=date(2026, 1, 1), end=date(2026, 2, 1),
            params={}, strategy_metrics={}, factor_report={}, created_at=date(2026, 6, 3))
    runs = st.list_recent(10)
    assert [r.signal for r in runs] == ["b", "a"]
```

`session` fixture 来自 `tests/conftest.py`(内存 sqlite + 模型已注册)。

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_backtest_store.py -v`
Expected: FAIL（ModuleNotFoundError: app.backtest.store）

- [ ] **Step 3: 实现**

在 `app/db/models.py` 末尾追加（`Integer/String/Float/Date/Index/Mapped/mapped_column/date` 已 import）:

```python
class BacktestRun(Base):
    __tablename__ = "backtest_runs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[date] = mapped_column(Date)
    signal: Mapped[str] = mapped_column(String(32))
    start: Mapped[date] = mapped_column(Date)
    end: Mapped[date] = mapped_column(Date)
    params: Mapped[str] = mapped_column(String, default="{}")            # JSON text
    strategy_metrics: Mapped[str] = mapped_column(String, default="{}")  # JSON text
    factor_report: Mapped[str] = mapped_column(String, default="{}")     # JSON text

    def params_dict(self) -> dict:
        import json
        return json.loads(self.params or "{}")

    def strategy_metrics_dict(self) -> dict:
        import json
        return json.loads(self.strategy_metrics or "{}")

    def factor_report_dict(self) -> dict:
        import json
        return json.loads(self.factor_report or "{}")


Index("ix_backtest_runs_created_at", BacktestRun.created_at)
```

新建 `app/backtest/store.py`:

```python
import json
from datetime import date
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.db.models import BacktestRun


class BacktestStore:
    def __init__(self, session: Session):
        self.s = session

    def save(self, *, signal: str, start: date, end: date, params: dict,
             strategy_metrics: dict, factor_report: dict,
             created_at: date) -> BacktestRun:
        run = BacktestRun(
            created_at=created_at, signal=signal, start=start, end=end,
            params=json.dumps(params, ensure_ascii=False),
            strategy_metrics=json.dumps(strategy_metrics, ensure_ascii=False),
            factor_report=json.dumps(factor_report, ensure_ascii=False))
        self.s.add(run)
        self.s.commit()
        return run

    def latest(self) -> BacktestRun | None:
        return self.s.scalar(
            select(BacktestRun).order_by(BacktestRun.id.desc()).limit(1))

    def list_recent(self, n: int = 10) -> list[BacktestRun]:
        return list(self.s.scalars(
            select(BacktestRun).order_by(BacktestRun.id.desc()).limit(n)))
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_backtest_store.py -v`
Expected: PASS（3 个）

- [ ] **Step 5: 提交**

```bash
git add app/db/models.py app/backtest/store.py tests/test_backtest_store.py
git commit -m "feat(backtest): BacktestRun model + BacktestStore (save/latest/list_recent)"
```

---

### Task 1: run_backtest 写库 + /api/backtest

**Files:**
- Create: `app/api/routes_backtest.py`
- Modify: `app/main.py`（注册 router)、`scripts/run_backtest.py`（跑完存库)
- Test: `tests/test_api_backtest.py`（新建）

- [ ] **Step 1: 写失败测试** — 新建 `tests/test_api_backtest.py`:

```python
from datetime import date
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.db.database import Base
import app.db.models  # noqa
from app.main import create_app
from app.api.deps import get_session
from app.backtest.store import BacktestStore


def _client():
    engine = create_engine("sqlite:///:memory:", future=True,
                           connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, expire_on_commit=False, future=True)()
    BacktestStore(s).save(signal="momentum", start=date(2026, 1, 2),
                          end=date(2026, 6, 1), params={"topk": 8},
                          strategy_metrics={"annualized_return": 0.15},
                          factor_report={"ic_mean": 0.07}, created_at=date(2026, 6, 3))
    app = create_app()
    app.dependency_overrides[get_session] = lambda: s
    return TestClient(app)


def test_get_latest_backtest():
    r = _client().get("/api/backtest")
    assert r.status_code == 200
    body = r.json()
    assert body["signal"] == "momentum"
    assert body["strategy_metrics"]["annualized_return"] == 0.15
    assert body["factor_report"]["ic_mean"] == 0.07


def test_get_backtest_404_when_empty():
    engine = create_engine("sqlite:///:memory:", future=True,
                           connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, expire_on_commit=False, future=True)()
    app = create_app()
    app.dependency_overrides[get_session] = lambda: s
    assert TestClient(app).get("/api/backtest").status_code == 404


def test_list_recent_runs():
    r = _client().get("/api/backtest/runs?n=5")
    assert r.status_code == 200
    assert len(r.json()) == 1 and r.json()[0]["signal"] == "momentum"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_api_backtest.py -v`
Expected: FAIL（404 / import error）

- [ ] **Step 3: 实现**

新建 `app/api/routes_backtest.py`:

```python
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.api.deps import get_session
from app.backtest.store import BacktestStore

router = APIRouter(prefix="/api", tags=["backtest"])


def _run_json(run):
    return {
        "id": run.id, "created_at": run.created_at.isoformat(),
        "signal": run.signal, "start": run.start.isoformat(),
        "end": run.end.isoformat(), "params": run.params_dict(),
        "strategy_metrics": run.strategy_metrics_dict(),
        "factor_report": run.factor_report_dict()}


@router.get("/backtest")
def latest_backtest(s: Session = Depends(get_session)):
    run = BacktestStore(s).latest()
    if run is None:
        raise HTTPException(status_code=404, detail="no backtest run")
    return _run_json(run)


@router.get("/backtest/runs")
def recent_backtests(n: int = 10, s: Session = Depends(get_session)):
    return [_run_json(r) for r in BacktestStore(s).list_recent(n)]
```

在 `app/main.py`:import 行加 `routes_backtest`,加 `app.include_router(routes_backtest.router)`。

在 `scripts/run_backtest.py`:import 加 `from datetime import date as _date`(若已 import date 则复用)与 `from app.backtest.store import BacktestStore`;加 `--no-save` 参数;在打印 `STRATEGY:` 之后、`BACKTEST_DONE` 之前追加:

```python
    if not args.no_save:
        BacktestStore(session).save(
            signal="momentum", start=start, end=end,
            params={"topk": 8, "window": args.window},
            strategy_metrics=bt, factor_report=rep, created_at=date.today())
        print("SAVED backtest run", flush=True)
```

并在 argparse 增加 `p.add_argument("--no-save", action="store_true")`。（`date` 已在 run_backtest.py 顶部 import。)

- [ ] **Step 4: 跑测试确认通过** + 脚本语法

Run: `.venv/bin/python -m pytest tests/test_api_backtest.py -v`
Expected: PASS（3 个）
Run: `.venv/bin/python -c "import ast; ast.parse(open('scripts/run_backtest.py').read()); print('ok')"` → `ok`

- [ ] **Step 5: 提交**

```bash
git add app/api/routes_backtest.py app/main.py scripts/run_backtest.py tests/test_api_backtest.py
git commit -m "feat(backtest): persist runs + GET /api/backtest(/runs)"
```

---

### Task 2: ResearchStore.list_latest + GET /api/research 列表

**Files:**
- Modify: `app/research/store.py`、`app/api/routes_research.py`
- Test: `tests/test_research_store.py`（追加）、`tests/test_api_research.py`（追加）

- [ ] **Step 1: 写失败测试** — 追加到 `tests/test_research_store.py`:

```python
def test_list_latest_one_per_code_newest(session):
    st = ResearchStore(session)
    st.upsert("600519.SH", date(2026, 6, 1), AnalyzedNote(0.1, "", "old"), "s")
    st.upsert("600519.SH", date(2026, 6, 3), AnalyzedNote(0.5, "", "new"), "s")
    st.upsert("000001.SZ", date(2026, 6, 2), AnalyzedNote(0.2, "", "x"), "s")
    rows = st.list_latest(10)
    # 每股一条最新;按 as_of 倒序 -> 600519(6/3) 在前
    assert [r.code for r in rows] == ["600519.SH", "000001.SZ"]
    assert rows[0].summary == "new"
```

追加到 `tests/test_api_research.py`（复用其顶部 import 与 `_client` 模式;若 `_client` 只 seed 一只股,新增独立 client）:

```python
def test_list_research_returns_latest_per_code():
    from datetime import date as _d
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool
    from app.db.database import Base
    import app.db.models  # noqa
    from app.main import create_app
    from app.api.deps import get_session
    from app.research.store import ResearchStore, AnalyzedNote
    from fastapi.testclient import TestClient
    engine = create_engine("sqlite:///:memory:", future=True,
                           connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, expire_on_commit=False, future=True)()
    ResearchStore(s).upsert("600519.SH", _d(2026, 6, 3), AnalyzedNote(0.5, "买入", "稳"), "x")
    app = create_app()
    app.dependency_overrides[get_session] = lambda: s
    r = TestClient(app).get("/api/research")
    assert r.status_code == 200
    assert r.json()[0]["code"] == "600519.SH" and r.json()[0]["sentiment"] == 0.5
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_research_store.py::test_list_latest_one_per_code_newest tests/test_api_research.py::test_list_research_returns_latest_per_code -v`
Expected: FAIL（AttributeError list_latest / 路由不存在)

- [ ] **Step 3: 实现**

在 `app/research/store.py` 的 `ResearchStore` 加方法(顶部已 import select、ResearchNote):

```python
    def list_latest(self, limit: int = 50) -> list:
        """每只股取最新一条笔记,按 as_of 倒序,最多 limit 条。"""
        rows = self.s.scalars(
            select(ResearchNote).order_by(ResearchNote.as_of.desc())).all()
        seen, out = set(), []
        for r in rows:
            if r.code in seen:
                continue
            seen.add(r.code)
            out.append(r)
            if len(out) >= limit:
                break
        return out
```

在 `app/api/routes_research.py` 增加列表端点(在 `get_research` 之前/之后均可,router 已有):

```python
@router.get("/research")
def list_research(s: Session = Depends(get_session)):
    return [{"code": n.code, "as_of": n.as_of.isoformat(),
             "sentiment": n.sentiment, "rating_consensus": n.rating_consensus,
             "summary": n.summary, "source": n.source}
            for n in ResearchStore(s).list_latest(50)]
```

（注意:`@router.get("/research/{code}")` 已存在;`/research` 与 `/research/{code}` 路由不冲突。)

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_research_store.py tests/test_api_research.py -v`
Expected: PASS（含原有 + 新增)

- [ ] **Step 5: 提交**

```bash
git add app/research/store.py app/api/routes_research.py tests/test_research_store.py tests/test_api_research.py
git commit -m "feat(research): list_latest + GET /api/research list endpoint"
```

- [ ] **Step 6: 后端全量回归**

Run: `.venv/bin/python -m pytest -q`
Expected: 全绿。

---

### Task 3: 前端装 antd + react-router + vitest

**Files:**
- Modify: `frontend/package.json`(deps)、`frontend/vite.config.ts`(vitest 配置)
- Create: `frontend/src/test/setup.ts`
- Test: `frontend/src/test/smoke.test.tsx`（新建,验证 vitest 跑通)

- [ ] **Step 1: 装依赖**

```bash
cd frontend
npm install antd react-router-dom
npm install -D vitest @testing-library/react @testing-library/jest-dom jsdom
```
Expected: 安装成功,package.json 出现这些依赖。

- [ ] **Step 2: 配 vitest**

把 `frontend/vite.config.ts` 改为:

```ts
/// <reference types="vitest/config" />
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: './src/test/setup.ts',
  },
})
```

新建 `frontend/src/test/setup.ts`:

```ts
import '@testing-library/jest-dom'
```

在 `frontend/package.json` 的 `scripts` 加:`"test": "vitest run"`。

- [ ] **Step 3: 写冒烟测试** — 新建 `frontend/src/test/smoke.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react'
import { describe, it, expect } from 'vitest'

describe('vitest setup', () => {
  it('renders a basic element', () => {
    render(<div>hello-backtest</div>)
    expect(screen.getByText('hello-backtest')).toBeInTheDocument()
  })
})
```

- [ ] **Step 4: 跑测试确认通过**

Run: `npm run test`
Expected: 1 passed。

- [ ] **Step 5: 提交**

```bash
git add frontend/package.json frontend/package-lock.json frontend/vite.config.ts frontend/src/test/
git commit -m "build(frontend): add antd + react-router + vitest setup"
```

---

### Task 4: App 壳 — antd Layout + Menu + react-router

**Files:**
- Modify: `frontend/src/main.tsx`(包 BrowserRouter)、`frontend/src/App.tsx`(Layout+路由)
- Test: `frontend/src/App.test.tsx`（新建）

说明:四页路由 `/`(看板)、`/screener`、`/research`、`/backtest`。本任务把现有 `Dashboard`/`ScreenerPool` 接入路由,研报/回测页用占位组件(后续任务填充)。

- [ ] **Step 1: 写失败测试** — 新建 `frontend/src/App.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import App from './App'

beforeEach(() => {
  vi.stubGlobal('fetch', vi.fn(() =>
    Promise.resolve({ ok: true, json: () => Promise.resolve([]) }) as any))
})

describe('App shell', () => {
  it('shows the four menu items', () => {
    render(<MemoryRouter><App /></MemoryRouter>)
    expect(screen.getByText('交易看板')).toBeInTheDocument()
    expect(screen.getByText('选股池')).toBeInTheDocument()
    expect(screen.getByText('研报')).toBeInTheDocument()
    expect(screen.getByText('回测')).toBeInTheDocument()
  })
})
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd frontend && npm run test -- App.test`
Expected: FAIL（App 尚未含菜单项/路由)

- [ ] **Step 3: 实现**

`frontend/src/main.tsx` 包 `BrowserRouter`:

```tsx
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import 'antd/dist/reset.css'
import './index.css'
import App from './App.tsx'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </StrictMode>,
)
```

`frontend/src/App.tsx` 重写为 antd Layout + Menu + Routes:

```tsx
import { Layout, Menu } from "antd";
import { Routes, Route, useNavigate, useLocation } from "react-router-dom";
import { Dashboard } from "./pages/Dashboard";
import { ScreenerPool } from "./pages/ScreenerPool";
import { ResearchPage } from "./pages/ResearchPage";
import { BacktestPage } from "./pages/BacktestPage";

const ITEMS = [
  { key: "/", label: "交易看板" },
  { key: "/screener", label: "选股池" },
  { key: "/research", label: "研报" },
  { key: "/backtest", label: "回测" },
];

export default function App() {
  const nav = useNavigate();
  const loc = useLocation();
  return (
    <Layout style={{ minHeight: "100vh" }}>
      <Layout.Sider theme="light" breakpoint="lg" collapsedWidth="0">
        <div style={{ height: 48, margin: 12, fontWeight: 700 }}>A股看板</div>
        <Menu mode="inline" selectedKeys={[loc.pathname]} items={ITEMS}
              onClick={(e) => nav(e.key)} />
      </Layout.Sider>
      <Layout>
        <Layout.Header style={{ background: "#fff", paddingLeft: 24,
          fontSize: 18, fontWeight: 600 }}>A股行情看板 + 多智能体交易</Layout.Header>
        <Layout.Content style={{ padding: 24 }}>
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/screener" element={<ScreenerPool />} />
            <Route path="/research" element={<ResearchPage />} />
            <Route path="/backtest" element={<BacktestPage />} />
          </Routes>
        </Layout.Content>
      </Layout>
    </Layout>
  );
}
```

新建占位页 `frontend/src/pages/ResearchPage.tsx`:

```tsx
export function ResearchPage() {
  return <div>研报页(待实现)</div>;
}
```

新建占位页 `frontend/src/pages/BacktestPage.tsx`:

```tsx
export function BacktestPage() {
  return <div>回测页(待实现)</div>;
}
```

（App.test.tsx 用 `MemoryRouter` 包裹,故 App 内不再自带 Router;main.tsx 用 `BrowserRouter`。)

- [ ] **Step 4: 跑测试确认通过 + 构建**

Run: `cd frontend && npm run test -- App.test`
Expected: PASS
Run: `npm run build`
Expected: tsc + vite 构建成功(占位页存在,类型通过)。

- [ ] **Step 5: 提交**

```bash
git add frontend/src/main.tsx frontend/src/App.tsx frontend/src/pages/ResearchPage.tsx frontend/src/pages/BacktestPage.tsx frontend/src/App.test.tsx
git commit -m "feat(frontend): antd Layout + Menu + react-router four-page shell"
```

---

### Task 5: 交易看板页 antd 化

**Files:**
- Modify: `frontend/src/pages/Dashboard.tsx`、`frontend/src/components/PositionsTable.tsx`、`frontend/src/components/DiscoveryPanel.tsx`、`frontend/src/components/DecisionsPanel.tsx`、`frontend/src/components/TradeForm.tsx`
- Test: `frontend/src/pages/Dashboard.test.tsx`（新建)

说明:用 antd `Statistic`/`Card`/`Row`/`Col`/`Table`/`Tag` 重构;`EquityChart`(ECharts)保留,套 `Card`。功能不变。

- [ ] **Step 1: 写失败测试** — 新建 `frontend/src/pages/Dashboard.test.tsx`:

```tsx
import { render, screen, waitFor } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { Dashboard } from './Dashboard'

beforeEach(() => {
  vi.stubGlobal('fetch', vi.fn((url: string) => {
    const body = url.includes('/api/account/')
      ? { id: 1, name: "测试", cash: 12345.6, positions: [] }
      : []
    return Promise.resolve({ ok: true, json: () => Promise.resolve(body) }) as any
  }))
})

describe('Dashboard', () => {
  it('shows cash as a statistic', async () => {
    render(<Dashboard />)
    await waitFor(() => expect(screen.getByText('现金')).toBeInTheDocument())
  })
})
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd frontend && npm run test -- Dashboard.test`
Expected: FAIL（现有 Dashboard 无 "现金" Statistic 标签,文案是 "现金: x")

- [ ] **Step 3: 实现**

重写 `frontend/src/pages/Dashboard.tsx`:

```tsx
import { useCallback, useEffect, useState } from "react";
import { Row, Col, Card, Statistic, Spin } from "antd";
import { apiGet } from "../api/client";
import { PositionsTable } from "../components/PositionsTable";
import { EquityChart } from "../components/EquityChart";
import { TradeForm } from "../components/TradeForm";
import { DiscoveryPanel } from "../components/DiscoveryPanel";
import { DecisionsPanel } from "../components/DecisionsPanel";

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

  if (!acc) return <Spin />;
  const mv = acc.positions.reduce((s, p) => s + p.shares * p.cost, 0);
  return (
    <div style={{ display: "grid", gap: 16 }}>
      <Row gutter={16}>
        <Col span={8}><Card><Statistic title="现金" value={acc.cash} precision={2} /></Card></Col>
        <Col span={8}><Card><Statistic title="持仓成本市值" value={mv} precision={2} /></Card></Col>
        <Col span={8}><Card><Statistic title="总(现金+持仓)" value={acc.cash + mv} precision={2} /></Card></Col>
      </Row>
      <Card title="下单(人机协同)"><TradeForm accountId={ACCOUNT_ID} onDone={load} /></Card>
      <Card title="持仓"><PositionsTable positions={acc.positions} /></Card>
      <Card title="净值曲线"><EquityChart points={eq} /></Card>
      <Card title="机会榜 Top-8"><DiscoveryPanel /></Card>
      <Card title="决策(人机协同)"><DecisionsPanel /></Card>
    </div>
  );
}
```

重写 `frontend/src/components/PositionsTable.tsx` 用 antd Table:

```tsx
import { Table } from "antd";

type Position = { code: string; shares: number; cost: number };

export function PositionsTable({ positions }: { positions: Position[] }) {
  const columns = [
    { title: "代码", dataIndex: "code", key: "code" },
    { title: "股数", dataIndex: "shares", key: "shares" },
    { title: "成本", dataIndex: "cost", key: "cost",
      render: (v: number) => v.toFixed(2) },
  ];
  return <Table rowKey="code" size="small" pagination={false}
                dataSource={positions} columns={columns} />;
}
```

重写 `frontend/src/components/DiscoveryPanel.tsx` 用 antd Table:

```tsx
import { useEffect, useState } from "react";
import { Table, Empty } from "antd";
import { apiGet } from "../api/client";

type Pick = { as_of: string; code: string; rank: number; score: number;
  factors: Record<string, number> };

export function DiscoveryPanel() {
  const [picks, setPicks] = useState<Pick[]>([]);
  useEffect(() => {
    apiGet<Pick[]>("/api/discovery").then(setPicks).catch(() => {});
  }, []);
  if (!picks.length) return <Empty description="机会榜暂无数据" />;
  const columns = [
    { title: "#", dataIndex: "rank", key: "rank" },
    { title: "代码", dataIndex: "code", key: "code" },
    { title: "评分", dataIndex: "score", key: "score",
      render: (v: number) => v.toFixed(3) },
    { title: "因子", dataIndex: "factors", key: "factors",
      render: (f: Record<string, number>) =>
        Object.entries(f).map(([k, v]) => `${k}:${v.toFixed(2)}`).join("  ") },
  ];
  return <Table rowKey="code" size="small" pagination={false}
                dataSource={picks} columns={columns} />;
}
```

重写 `frontend/src/components/DecisionsPanel.tsx` 用 antd(保留 approve/reject + 理由):

```tsx
import { useCallback, useEffect, useState } from "react";
import { Table, Tag, Button, Space, Empty, Typography } from "antd";
import { apiGet, apiPost } from "../api/client";

type Decision = { id: number; code: string; action: string; confidence: number;
  shares: number; status: string; reasoning: string };

export function DecisionsPanel() {
  const [rows, setRows] = useState<Decision[]>([]);
  const load = useCallback(() => {
    apiGet<Decision[]>("/api/decisions").then(setRows).catch(() => {});
  }, []);
  useEffect(load, [load]);

  async function act(id: number, what: "approve" | "reject") {
    await apiPost(`/api/decisions/${id}/${what}`, what === "approve" ? { price: 0 } : {});
    load();
  }
  if (!rows.length) return <Empty description="暂无决策" />;
  const color: Record<string, string> = { BUY: "red", SELL: "green", HOLD: "default" };
  const columns = [
    { title: "代码", dataIndex: "code", key: "code" },
    { title: "动作", dataIndex: "action", key: "action",
      render: (a: string) => <Tag color={color[a] || "default"}>{a}</Tag> },
    { title: "信心", dataIndex: "confidence", key: "confidence",
      render: (v: number) => v.toFixed(2) },
    { title: "股数", dataIndex: "shares", key: "shares" },
    { title: "状态", dataIndex: "status", key: "status" },
    { title: "操作", key: "act", render: (_: unknown, d: Decision) =>
        d.status === "PENDING" ? (
          <Space>
            <Button size="small" type="primary" onClick={() => act(d.id, "approve")}>批准</Button>
            <Button size="small" danger onClick={() => act(d.id, "reject")}>驳回</Button>
          </Space>) : null },
  ];
  return (
    <Table rowKey="id" size="small" pagination={false} dataSource={rows} columns={columns}
      expandable={{ expandedRowRender: (d) =>
        <Typography.Paragraph style={{ whiteSpace: "pre-wrap", margin: 0 }}>
          {d.reasoning}</Typography.Paragraph> }} />
  );
}
```

重写 `frontend/src/components/TradeForm.tsx` 用 antd Form。**请求保持与现有完全一致**:POST `/api/trade`,body `{account_id, code, side, price, shares, on}`(`on` = 今天 `YYYY-MM-DD`)。只换 UI,不改请求:

```tsx
import { Form, InputNumber, Input, Select, Button, message } from "antd";
import { apiPost } from "../api/client";

export function TradeForm({ accountId, onDone }:
  { accountId: number; onDone: () => void }) {
  const [form] = Form.useForm();
  async function submit(v: { code: string; side: string; price: number; shares: number }) {
    try {
      await apiPost("/api/trade", {
        account_id: accountId, code: v.code, side: v.side,
        price: v.price, shares: v.shares,
        on: new Date().toISOString().slice(0, 10),
      });
      message.success("成交");
      form.resetFields();
      onDone();
    } catch (e) {
      message.error("失败: " + (e as Error).message);
    }
  }
  return (
    <Form form={form} layout="inline" onFinish={submit}
          initialValues={{ code: "600519.SH", side: "BUY", price: 1500, shares: 100 }}>
      <Form.Item name="code" rules={[{ required: true }]}>
        <Input placeholder="代码 如 600519.SH" /></Form.Item>
      <Form.Item name="side"><Select style={{ width: 90 }}
        options={[{ value: "BUY", label: "买入" }, { value: "SELL", label: "卖出" }]} /></Form.Item>
      <Form.Item name="price" rules={[{ required: true }]}>
        <InputNumber placeholder="价格" min={0} /></Form.Item>
      <Form.Item name="shares" rules={[{ required: true }]}>
        <InputNumber placeholder="股数" min={0} step={100} /></Form.Item>
      <Form.Item><Button type="primary" htmlType="submit">下单</Button></Form.Item>
    </Form>
  );
}
```

- [ ] **Step 4: 跑测试 + 构建**

Run: `cd frontend && npm run test -- Dashboard.test` → PASS
Run: `npm run build` → 成功(tsc 类型通过)

- [ ] **Step 5: 提交**

```bash
git add frontend/src/pages/Dashboard.tsx frontend/src/components/
git commit -m "feat(frontend): antd-ify dashboard (Statistic/Card/Table/Form/Tag)"
```

---

### Task 6: 选股池页 antd 化

**Files:**
- Modify: `frontend/src/pages/ScreenerPool.tsx`、`frontend/src/components/PicksTable.tsx`
- Test: `frontend/src/pages/ScreenerPool.test.tsx`（新建)

- [ ] **Step 1: 写失败测试** — 新建 `frontend/src/pages/ScreenerPool.test.tsx`:

```tsx
import { render, screen, waitFor } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { ScreenerPool } from './ScreenerPool'

beforeEach(() => {
  vi.stubGlobal('fetch', vi.fn(() => Promise.resolve({ ok: true,
    json: () => Promise.resolve([{ code: "600519.SH", theme: "白酒",
      first_selected_on: "2026-06-01", entry_close: 1800,
      ret_t1: 0.01, ret_t3: 0.02, ret_t5: null, ret_t10: null }]) }) as any))
})

describe('ScreenerPool', () => {
  it('renders a pick row', async () => {
    render(<ScreenerPool />)
    await waitFor(() => expect(screen.getByText('600519.SH')).toBeInTheDocument())
  })
})
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd frontend && npm run test -- ScreenerPool.test`
Expected: FAIL 或 PASS-by-accident;先确认现状。若现有 `PicksTable` 已渲染代码文本可能 PASS —— 那么改测试断言 antd 表格特性:加 `expect(document.querySelector('.ant-table')).toBeTruthy()` 使其在 antd 化前 FAIL。

- [ ] **Step 3: 实现**

重写 `frontend/src/components/PicksTable.tsx`:

```tsx
import { Table, Tag, Empty } from "antd";

type Pick = {
  code: string; theme: string; first_selected_on: string; entry_close: number;
  ret_t1: number | null; ret_t3: number | null;
  ret_t5: number | null; ret_t10: number | null;
};

const pct = (v: number | null) => v == null ? "-" : `${(v * 100).toFixed(1)}%`;

export function PicksTable({ picks }: { picks: Pick[] }) {
  if (!picks.length) return <Empty description="选股池暂无数据" />;
  const columns = [
    { title: "代码", dataIndex: "code", key: "code" },
    { title: "题材", dataIndex: "theme", key: "theme",
      render: (t: string) => <Tag color="blue">{t}</Tag> },
    { title: "入选日", dataIndex: "first_selected_on", key: "d" },
    { title: "入选价", dataIndex: "entry_close", key: "p",
      render: (v: number) => v.toFixed(2) },
    { title: "T+1", dataIndex: "ret_t1", key: "t1", render: pct },
    { title: "T+3", dataIndex: "ret_t3", key: "t3", render: pct },
    { title: "T+5", dataIndex: "ret_t5", key: "t5", render: pct },
    { title: "T+10", dataIndex: "ret_t10", key: "t10", render: pct },
  ];
  return <Table rowKey={(r) => `${r.code}-${r.first_selected_on}`} size="small"
                pagination={false} dataSource={picks} columns={columns} />;
}
```

重写 `frontend/src/pages/ScreenerPool.tsx`:

```tsx
import { useEffect, useState } from "react";
import { Card } from "antd";
import { apiGet } from "../api/client";
import { PicksTable } from "../components/PicksTable";

type Pick = {
  code: string; theme: string; first_selected_on: string; entry_close: number;
  ret_t1: number | null; ret_t3: number | null;
  ret_t5: number | null; ret_t10: number | null;
};

export function ScreenerPool() {
  const [picks, setPicks] = useState<Pick[]>([]);
  useEffect(() => {
    apiGet<Pick[]>("/api/screener/picks").then(setPicks).catch(() => {});
  }, []);
  return <Card title="题材选股池(T+1/3/5/10 追踪)"><PicksTable picks={picks} /></Card>;
}
```

- [ ] **Step 4: 跑测试 + 构建**

Run: `cd frontend && npm run test -- ScreenerPool.test` → PASS
Run: `npm run build` → 成功

- [ ] **Step 5: 提交**

```bash
git add frontend/src/pages/ScreenerPool.tsx frontend/src/components/PicksTable.tsx frontend/src/pages/ScreenerPool.test.tsx
git commit -m "feat(frontend): antd-ify screener pool table"
```

---

### Task 7: 研报展示页

**Files:**
- Modify: `frontend/src/pages/ResearchPage.tsx`(替换占位)
- Test: `frontend/src/pages/ResearchPage.test.tsx`（新建)

说明:左侧 antd `Table` 列出有研报的股(`GET /api/research`),点行右侧 `Card` 展示 sentiment(`Statistic`)、评级、摘要。

- [ ] **Step 1: 写失败测试** — 新建 `frontend/src/pages/ResearchPage.test.tsx`:

```tsx
import { render, screen, waitFor } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { ResearchPage } from './ResearchPage'

beforeEach(() => {
  vi.stubGlobal('fetch', vi.fn(() => Promise.resolve({ ok: true,
    json: () => Promise.resolve([{ code: "600519.SH", as_of: "2026-06-03",
      sentiment: 0.6, rating_consensus: "买入", summary: "机构看多茅台" }]) }) as any))
})

describe('ResearchPage', () => {
  it('lists a researched stock', async () => {
    render(<ResearchPage />)
    await waitFor(() => expect(screen.getByText('600519.SH')).toBeInTheDocument())
  })
})
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd frontend && npm run test -- ResearchPage.test`
Expected: FAIL（占位页无该文本)

- [ ] **Step 3: 实现** — 替换 `frontend/src/pages/ResearchPage.tsx`:

```tsx
import { useEffect, useState } from "react";
import { Row, Col, Card, Table, Statistic, Tag, Empty, Typography } from "antd";
import { apiGet } from "../api/client";

type Note = { code: string; as_of: string; sentiment: number;
  rating_consensus: string; summary: string };

export function ResearchPage() {
  const [notes, setNotes] = useState<Note[]>([]);
  const [sel, setSel] = useState<Note | null>(null);
  useEffect(() => {
    apiGet<Note[]>("/api/research").then((n) => {
      setNotes(n); setSel(n[0] ?? null);
    }).catch(() => {});
  }, []);

  const columns = [
    { title: "代码", dataIndex: "code", key: "code" },
    { title: "情绪", dataIndex: "sentiment", key: "s",
      render: (v: number) => <Tag color={v > 0.1 ? "red" : v < -0.1 ? "green" : "default"}>
        {v.toFixed(2)}</Tag> },
    { title: "日期", dataIndex: "as_of", key: "d" },
  ];
  return (
    <Row gutter={16}>
      <Col span={10}>
        <Card title="研报覆盖个股">
          {notes.length ? (
            <Table rowKey="code" size="small" pagination={false} dataSource={notes}
              columns={columns}
              onRow={(r) => ({ onClick: () => setSel(r), style: { cursor: "pointer" } })} />
          ) : <Empty description="暂无研报,先跑 run_research.py" />}
        </Card>
      </Col>
      <Col span={14}>
        {sel ? (
          <Card title={`${sel.code} 研报观点(${sel.as_of})`}>
            <Statistic title="情绪分(-1~1)" value={sel.sentiment} precision={2} />
            <p style={{ marginTop: 12 }}><b>评级共识:</b>{sel.rating_consensus || "—"}</p>
            <Typography.Paragraph style={{ whiteSpace: "pre-wrap" }}>
              {sel.summary}</Typography.Paragraph>
          </Card>
        ) : <Empty description="选择左侧个股查看研报" />}
      </Col>
    </Row>
  );
}
```

- [ ] **Step 4: 跑测试 + 构建**

Run: `cd frontend && npm run test -- ResearchPage.test` → PASS
Run: `npm run build` → 成功

- [ ] **Step 5: 提交**

```bash
git add frontend/src/pages/ResearchPage.tsx frontend/src/pages/ResearchPage.test.tsx
git commit -m "feat(frontend): research page (sentiment/rating/summary)"
```

---

### Task 8: 回测展示页

**Files:**
- Modify: `frontend/src/pages/BacktestPage.tsx`(替换占位)
- Create: `frontend/src/components/LayerBars.tsx`(分层收益 ECharts 柱状)
- Test: `frontend/src/pages/BacktestPage.test.tsx`（新建)

说明:`GET /api/backtest` 取最新 run;指标 `Statistic` 卡 + 因子 IC + 分层柱状(ECharts)+ run 元信息 `Descriptions`。无数据 `Empty`。

- [ ] **Step 1: 写失败测试** — 新建 `frontend/src/pages/BacktestPage.test.tsx`:

```tsx
import { render, screen, waitFor } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { BacktestPage } from './BacktestPage'

const RUN = {
  id: 1, created_at: "2026-06-03", signal: "momentum",
  start: "2026-01-02", end: "2026-06-01", params: { topk: 8 },
  strategy_metrics: { annualized_return: 0.15, information_ratio: 1.2,
    max_drawdown: -0.08, cum_return: 0.22 },
  factor_report: { ic_mean: 0.07, rank_ic_mean: 0.03,
    layer_returns: [-0.004, -0.002, 0.0, 0.001, 0.003] },
}

beforeEach(() => {
  vi.stubGlobal('fetch', vi.fn(() => Promise.resolve({ ok: true,
    json: () => Promise.resolve(RUN) }) as any))
})

describe('BacktestPage', () => {
  it('shows strategy metrics', async () => {
    render(<BacktestPage />)
    await waitFor(() => expect(screen.getByText('年化收益')).toBeInTheDocument())
  })
})
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd frontend && npm run test -- BacktestPage.test`
Expected: FAIL（占位页无 "年化收益")

- [ ] **Step 3: 实现**

新建 `frontend/src/components/LayerBars.tsx`(参考现有 `EquityChart` 的 ECharts 用法 —— 先 `cat frontend/src/components/EquityChart.tsx` 对齐 import/init 写法):

```tsx
import { useEffect, useRef } from "react";
import * as echarts from "echarts";

export function LayerBars({ layers }: { layers: number[] }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!ref.current) return;
    const chart = echarts.init(ref.current);
    chart.setOption({
      xAxis: { type: "category",
        data: layers.map((_, i) => `L${i + 1}`) },
      yAxis: { type: "value", axisLabel: { formatter: (v: number) => `${(v * 100).toFixed(1)}%` } },
      series: [{ type: "bar", data: layers.map((v) => +(v * 100).toFixed(2)) }],
      tooltip: { trigger: "axis" },
    });
    const onResize = () => chart.resize();
    window.addEventListener("resize", onResize);
    return () => { window.removeEventListener("resize", onResize); chart.dispose(); };
  }, [layers]);
  return <div ref={ref} style={{ height: 280 }} />;
}
```

替换 `frontend/src/pages/BacktestPage.tsx`:

```tsx
import { useEffect, useState } from "react";
import { Row, Col, Card, Statistic, Descriptions, Empty } from "antd";
import { apiGet } from "../api/client";
import { LayerBars } from "../components/LayerBars";

type Run = {
  id: number; created_at: string; signal: string; start: string; end: string;
  params: Record<string, unknown>;
  strategy_metrics: { annualized_return?: number; information_ratio?: number;
    max_drawdown?: number; cum_return?: number };
  factor_report: { ic_mean?: number; rank_ic_mean?: number; layer_returns?: number[] };
};

export function BacktestPage() {
  const [run, setRun] = useState<Run | null>(null);
  const [missing, setMissing] = useState(false);
  useEffect(() => {
    apiGet<Run>("/api/backtest").then(setRun).catch(() => setMissing(true));
  }, []);
  if (missing) return <Empty description="暂无回测结果,先跑 scripts/run_backtest.py" />;
  if (!run) return null;
  const m = run.strategy_metrics, f = run.factor_report;
  const pct = (v?: number) => v == null ? "-" : `${(v * 100).toFixed(2)}%`;
  return (
    <div style={{ display: "grid", gap: 16 }}>
      <Row gutter={16}>
        <Col span={6}><Card><Statistic title="年化收益" value={pct(m.annualized_return)} /></Card></Col>
        <Col span={6}><Card><Statistic title="信息比率(vs沪深300)" value={m.information_ratio ?? "-"}
          precision={2} /></Card></Col>
        <Col span={6}><Card><Statistic title="最大回撤" value={pct(m.max_drawdown)} /></Card></Col>
        <Col span={6}><Card><Statistic title="累计收益" value={pct(m.cum_return)} /></Card></Col>
      </Row>
      <Card title="因子 IC">
        <Row gutter={16}>
          <Col span={8}><Statistic title="IC 均值" value={f.ic_mean ?? "-"} precision={4} /></Col>
          <Col span={8}><Statistic title="RankIC 均值" value={f.rank_ic_mean ?? "-"} precision={4} /></Col>
        </Row>
        <div style={{ marginTop: 16 }}>
          {f.layer_returns?.length
            ? <LayerBars layers={f.layer_returns} />
            : <Empty description="无分层数据" />}
        </div>
      </Card>
      <Descriptions title="回测元信息" bordered size="small" column={2}>
        <Descriptions.Item label="信号">{run.signal}</Descriptions.Item>
        <Descriptions.Item label="区间">{run.start} ~ {run.end}</Descriptions.Item>
        <Descriptions.Item label="参数">{JSON.stringify(run.params)}</Descriptions.Item>
        <Descriptions.Item label="生成于">{run.created_at}</Descriptions.Item>
      </Descriptions>
    </div>
  );
}
```

- [ ] **Step 4: 跑测试 + 构建**

Run: `cd frontend && npm run test -- BacktestPage.test` → PASS
Run: `npm run build` → 成功

- [ ] **Step 5: 提交**

```bash
git add frontend/src/pages/BacktestPage.tsx frontend/src/components/LayerBars.tsx frontend/src/pages/BacktestPage.test.tsx
git commit -m "feat(frontend): backtest page (metric cards + IC + layered bars)"
```

---

### Task 9: 全量验证 + 人工跑通

**Files:** 无新增(验证 + 可能的小修)

- [ ] **Step 1: 前端全量测试 + 构建**

```bash
cd frontend
npm run test          # 全部 vitest 通过
npm run build         # tsc + vite 构建成功,无类型错误
```
Expected: 测试全绿;`dist/` 产出。若 tsc 报未用 import / 类型错,就地修干净。

- [ ] **Step 2: 后端全量测试**

```bash
cd ../backend
.venv/bin/python -m pytest -q
```
Expected: 全绿。

- [ ] **Step 3: 起服务人工跑通(冒烟)**

```bash
cd backend && setsid bash -c '.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000 > /tmp/uvicorn.log 2>&1' </dev/null &
cd ../frontend && setsid bash -c 'npm run dev -- --host 0.0.0.0 --port 5173 > /tmp/vite.log 2>&1' </dev/null &
```
人工/截图核对四页能切换、看板统计卡与表格渲染、研报页选股、回测页(若已有 run)出指标。确认无控制台报错。可先 `cd backend && .venv/bin/python scripts/run_backtest.py --qlib-dir /tmp/qlib_cn --start 2026-05-06 --end 2026-05-28` 造一条 run 供回测页展示(/tmp/qlib_cn 是切片5回测冒烟留下的 30 股库)。

- [ ] **Step 4: 提交(若 Step 1 有修)**

```bash
git add -A && git commit -m "chore(frontend): fix build/type issues, verify all pages render"
```

---

## 完成标准

- 后端 `pytest -q` 全绿(新增 backtest store/api + research list ~8 测试)。
- 前端 `npm run test`(vitest)全绿、`npm run build` 成功。
- 四页路由可切换;看板/选股池 antd 化;研报页、回测页能展示对应数据(空数据有 Empty 引导)。
- 回测结果经 run_backtest 落库,`/api/backtest` 可取。
- 分支 `slice-5-dashboard`,逐任务提交,待用户决定合并/推送(PAT 见项目记忆)。
