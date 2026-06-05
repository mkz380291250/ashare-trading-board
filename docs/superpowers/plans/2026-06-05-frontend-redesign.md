# 前端深度改版 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把前端改成响应式(桌面侧栏 / 手机底部 TabBar + 宽表转卡片)+ 深浅双主题(默认深色可切换持久化)+ 统一视觉(靛蓝 `#5b8cff` + 红涨绿跌语义色)。

**Architecture:** 新增 `ThemeProvider`(Context + antd ConfigProvider + localStorage)与 `theme/tokens.ts`(两套 ThemeConfig + 语义色);重写 `App.tsx` 为响应式骨架,用 `Grid.useBreakpoint` 在桌面侧栏与手机底部 TabBar(+"更多"抽屉)间切换;新增 `ResponsiveList`(桌面 antd Table、手机卡片列表)统一替换会溢出的宽表;逐页把写死 `Col span` 改为响应式 `xs/md`。不改任何后端或业务逻辑。

**Tech Stack:** React + TypeScript + antd 6.4 + react-router-dom + vitest(jsdom)。

---

## 通用约定

- 运行单测:`cd frontend && npx vitest run <path>`;全量:`npx vitest run`;构建:`npm run build`。
- jsdom 下 `matchMedia` 被 stub(`matches:false`),`Grid.useBreakpoint()` 各断点为假 → 默认判为「移动态」。因此**所有依赖断点的组件都接受可选 `forceMobile?: boolean` 测试钩子**(`undefined` 时走真实断点)。桌面态测试传 `forceMobile={false}`,移动态传 `forceMobile={true}`。
- 提交只 `git add` 本任务列出的文件,**不要** `git add -A`。
- 现有测试 setup 在 `src/test/setup.ts`(已 stub matchMedia/canvas),勿改。

## 文件结构

- Create `src/theme/tokens.ts` — 两套 ThemeConfig + 语义色常量/helper
- Create `src/theme/ThemeProvider.tsx` — 主题 Context + ConfigProvider + localStorage
- Create `src/components/ThemeToggle.tsx` — 深浅切换开关
- Create `src/components/ResponsiveList.tsx` — 桌面表格 / 手机卡片
- Create `src/components/SideNav.tsx` — 桌面侧栏菜单
- Create `src/components/BottomTabBar.tsx` — 手机底部 Tab
- Create `src/components/MoreDrawer.tsx` — "更多"抽屉
- Modify `src/main.tsx` — 包 ThemeProvider
- Modify `src/App.tsx` — 响应式骨架
- Modify 页面与表格组件 — 响应式栅格 + 接入 ResponsiveList

---

### Task 1: 主题系统(tokens + ThemeProvider + ThemeToggle + main 接线)

**Files:**
- Create: `src/theme/tokens.ts`
- Create: `src/theme/ThemeProvider.tsx`
- Create: `src/components/ThemeToggle.tsx`
- Test: `src/theme/ThemeProvider.test.tsx`
- Modify: `src/main.tsx`

- [ ] **Step 1: Write the failing test** — `src/theme/ThemeProvider.test.tsx`

```tsx
import { render, screen, act } from "@testing-library/react";
import { describe, it, expect, beforeEach } from "vitest";
import { ThemeProvider, useTheme } from "./ThemeProvider";

function Probe() {
  const { isDark, toggle } = useTheme();
  return <button onClick={toggle}>{isDark ? "dark" : "light"}</button>;
}

beforeEach(() => localStorage.clear());

describe("ThemeProvider", () => {
  it("defaults to dark", () => {
    render(<ThemeProvider><Probe /></ThemeProvider>);
    expect(screen.getByRole("button").textContent).toBe("dark");
  });

  it("toggle flips theme and persists to localStorage", () => {
    render(<ThemeProvider><Probe /></ThemeProvider>);
    act(() => screen.getByRole("button").click());
    expect(screen.getByRole("button").textContent).toBe("light");
    expect(localStorage.getItem("ui-theme")).toBe("light");
  });

  it("reads initial theme from localStorage", () => {
    localStorage.setItem("ui-theme", "light");
    render(<ThemeProvider><Probe /></ThemeProvider>);
    expect(screen.getByRole("button").textContent).toBe("light");
  });
});
```

- [ ] **Step 2: Run, expect FAIL** — `npx vitest run src/theme/ThemeProvider.test.tsx` (module not found)

- [ ] **Step 3: Implement** — `src/theme/tokens.ts`:

```ts
import { theme, type ThemeConfig } from "antd";

const BRAND = "#5b8cff";
const SHARED = { colorPrimary: BRAND, borderRadius: 10,
  fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'PingFang SC', 'Microsoft YaHei', sans-serif" };

export const darkTheme: ThemeConfig = {
  algorithm: theme.darkAlgorithm,
  token: { ...SHARED, colorBgLayout: "#0f1115", colorBgContainer: "#171a21" },
};

export const lightTheme: ThemeConfig = {
  algorithm: theme.defaultAlgorithm,
  token: { ...SHARED, colorBgLayout: "#f5f7fb", colorBgContainer: "#ffffff" },
};

// A股红涨绿跌:与 antd 主题解耦的语义色
export const UP = "#f5222d";
export const DOWN = "#13c281";
export function semanticColor(v: number | null | undefined): string | undefined {
  if (v == null || v === 0) return undefined;       // undefined => antd 默认(灰)
  return v > 0 ? UP : DOWN;
}
```

`src/theme/ThemeProvider.tsx`:

```tsx
import { createContext, useContext, useState, useCallback, type ReactNode } from "react";
import { ConfigProvider } from "antd";
import { darkTheme, lightTheme } from "./tokens";

type Ctx = { isDark: boolean; toggle: () => void };
const ThemeCtx = createContext<Ctx>({ isDark: true, toggle: () => {} });
export const useTheme = () => useContext(ThemeCtx);

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [isDark, setIsDark] = useState(
    () => (localStorage.getItem("ui-theme") ?? "dark") !== "light");
  const toggle = useCallback(() => {
    setIsDark((d) => {
      const next = !d;
      localStorage.setItem("ui-theme", next ? "dark" : "light");
      return next;
    });
  }, []);
  return (
    <ThemeCtx.Provider value={{ isDark, toggle }}>
      <ConfigProvider theme={isDark ? darkTheme : lightTheme}>{children}</ConfigProvider>
    </ThemeCtx.Provider>
  );
}
```

`src/components/ThemeToggle.tsx`:

```tsx
import { Switch } from "antd";
import { useTheme } from "../theme/ThemeProvider";

export function ThemeToggle() {
  const { isDark, toggle } = useTheme();
  return <Switch checked={isDark} onChange={toggle}
    checkedChildren="🌙" unCheckedChildren="☀️" aria-label="切换主题" />;
}
```

- [ ] **Step 4: Run, expect PASS** — `npx vitest run src/theme/ThemeProvider.test.tsx`

- [ ] **Step 5: Wire main.tsx** — replace its body so `ThemeProvider` wraps `App` (keep BrowserRouter, drop the static reset.css only if present; keep it):

```tsx
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import 'antd/dist/reset.css'
import './index.css'
import App from './App.tsx'
import { ThemeProvider } from './theme/ThemeProvider'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <BrowserRouter>
      <ThemeProvider>
        <App />
      </ThemeProvider>
    </BrowserRouter>
  </StrictMode>,
)
```

- [ ] **Step 6: Commit**

```bash
git add src/theme/tokens.ts src/theme/ThemeProvider.tsx src/components/ThemeToggle.tsx src/theme/ThemeProvider.test.tsx src/main.tsx
git commit -m "feat(frontend): dual-theme system (ThemeProvider + tokens + toggle), default dark"
```

---

### Task 2: ResponsiveList(桌面表格 / 手机卡片)

**Files:**
- Create: `src/components/ResponsiveList.tsx`
- Test: `src/components/ResponsiveList.test.tsx`

- [ ] **Step 1: Write the failing test** — `src/components/ResponsiveList.test.tsx`

```tsx
import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { ResponsiveList } from "./ResponsiveList";

type Row = { code: string; name: string };
const DATA: Row[] = [{ code: "600519.SH", name: "贵州茅台" }];
const columns = [
  { title: "代码", dataIndex: "code", key: "code" },
  { title: "名称", dataIndex: "name", key: "name" },
];

describe("ResponsiveList", () => {
  it("desktop renders a table (column headers visible)", () => {
    render(<ResponsiveList forceMobile={false} dataSource={DATA} columns={columns}
      rowKey="code" renderCard={(r: Row) => <div>card-{r.code}</div>} />);
    expect(screen.getByText("代码")).toBeInTheDocument();   // 表头
    expect(screen.getByText("贵州茅台")).toBeInTheDocument();
  });

  it("mobile renders cards via renderCard", () => {
    render(<ResponsiveList forceMobile={true} dataSource={DATA} columns={columns}
      rowKey="code" renderCard={(r: Row) => <div>card-{r.code}</div>} />);
    expect(screen.getByText("card-600519.SH")).toBeInTheDocument();
    expect(screen.queryByText("代码")).toBeNull();          // 无表头
  });

  it("shows empty node when no data", () => {
    render(<ResponsiveList forceMobile={true} dataSource={[]} columns={columns}
      rowKey="code" renderCard={() => null} empty={<div>空空如也</div>} />);
    expect(screen.getByText("空空如也")).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run, expect FAIL** — `npx vitest run src/components/ResponsiveList.test.tsx`

- [ ] **Step 3: Implement** — `src/components/ResponsiveList.tsx`:

```tsx
import { type ReactNode } from "react";
import { Table, Grid, Space, Empty } from "antd";
import type { ColumnsType } from "antd/es/table";

type Props<T> = {
  dataSource: T[];
  columns: ColumnsType<T>;
  rowKey: string | ((r: T) => string);
  renderCard: (record: T) => ReactNode;
  onRowClick?: (record: T) => void;
  empty?: ReactNode;
  forceMobile?: boolean;
};

export function ResponsiveList<T extends object>(p: Props<T>) {
  const screens = Grid.useBreakpoint();
  const isMobile = p.forceMobile ?? !screens.md;
  const keyOf = (r: T, i: number) =>
    typeof p.rowKey === "function" ? p.rowKey(r) : String((r as Record<string, unknown>)[p.rowKey] ?? i);

  if (!p.dataSource.length) return <>{p.empty ?? <Empty description="暂无数据" />}</>;

  if (isMobile) {
    return (
      <Space direction="vertical" size="small" style={{ width: "100%" }}>
        {p.dataSource.map((r, i) => (
          <div key={keyOf(r, i)} onClick={() => p.onRowClick?.(r)}
            style={p.onRowClick ? { cursor: "pointer" } : undefined}>
            {p.renderCard(r)}
          </div>
        ))}
      </Space>
    );
  }
  return (
    <Table<T> rowKey={p.rowKey} size="small" pagination={false}
      dataSource={p.dataSource} columns={p.columns} scroll={{ x: "max-content" }}
      onRow={(r) => ({ onClick: () => p.onRowClick?.(r),
        style: p.onRowClick ? { cursor: "pointer" } : undefined })} />
  );
}
```

- [ ] **Step 4: Run, expect PASS** — `npx vitest run src/components/ResponsiveList.test.tsx`

- [ ] **Step 5: Commit**

```bash
git add src/components/ResponsiveList.tsx src/components/ResponsiveList.test.tsx
git commit -m "feat(frontend): ResponsiveList (desktop table / mobile cards)"
```

---

### Task 3: 导航组件(SideNav + BottomTabBar + MoreDrawer)

**Files:**
- Create: `src/components/SideNav.tsx`
- Create: `src/components/BottomTabBar.tsx`
- Create: `src/components/MoreDrawer.tsx`
- Test: `src/components/BottomTabBar.test.tsx`

导航项集中定义在 `SideNav.tsx` 并导出复用。主导航 5 项 + "更多" 2 项:

- [ ] **Step 1: Write the failing test** — `src/components/BottomTabBar.test.tsx`

```tsx
import { render, screen, fireEvent } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, it, expect, vi } from "vitest";
import { BottomTabBar } from "./BottomTabBar";

describe("BottomTabBar", () => {
  it("renders the 5 primary tabs + 更多", () => {
    render(<MemoryRouter><BottomTabBar onMore={vi.fn()} /></MemoryRouter>);
    ["看板", "选股", "跟踪", "决策", "更多"].forEach((t) =>
      expect(screen.getByText(t)).toBeInTheDocument());
  });

  it("calls onMore when 更多 tapped", () => {
    const onMore = vi.fn();
    render(<MemoryRouter><BottomTabBar onMore={onMore} /></MemoryRouter>);
    fireEvent.click(screen.getByText("更多"));
    expect(onMore).toHaveBeenCalled();
  });
});
```

- [ ] **Step 2: Run, expect FAIL** — `npx vitest run src/components/BottomTabBar.test.tsx`

- [ ] **Step 3: Implement** — `src/components/SideNav.tsx`:

```tsx
import { Menu } from "antd";
import { useNavigate, useLocation } from "react-router-dom";
import {
  DashboardOutlined, FundOutlined, EyeOutlined, RobotOutlined,
  FileTextOutlined, LineChartOutlined,
} from "@ant-design/icons";

export const NAV_PRIMARY = [
  { key: "/", label: "看板", icon: <DashboardOutlined /> },
  { key: "/screener", label: "选股", icon: <FundOutlined /> },
  { key: "/track", label: "跟踪", icon: <EyeOutlined /> },
  { key: "/decisions", label: "决策", icon: <RobotOutlined /> },
];
export const NAV_MORE = [
  { key: "/research", label: "研报", icon: <FileTextOutlined /> },
  { key: "/backtest", label: "回测", icon: <LineChartOutlined /> },
];
export const NAV_ALL = [...NAV_PRIMARY, ...NAV_MORE];

export function SideNav() {
  const nav = useNavigate();
  const loc = useLocation();
  return (
    <Menu mode="inline" selectedKeys={[loc.pathname]} items={NAV_ALL}
      onClick={(e) => nav(e.key)} style={{ borderInlineEnd: "none" }} />
  );
}
```

`src/components/BottomTabBar.tsx`:

```tsx
import { useNavigate, useLocation } from "react-router-dom";
import { AppstoreOutlined } from "@ant-design/icons";
import { NAV_PRIMARY } from "./SideNav";

export function BottomTabBar({ onMore }: { onMore: () => void }) {
  const nav = useNavigate();
  const loc = useLocation();
  const items = [...NAV_PRIMARY, { key: "__more", label: "更多", icon: <AppstoreOutlined /> }];
  return (
    <div style={{ position: "fixed", bottom: 0, left: 0, right: 0, height: 56,
      display: "flex", borderTop: "1px solid rgba(128,128,128,0.2)",
      background: "var(--ant-color-bg-container, #171a21)", zIndex: 100 }}>
      {items.map((it) => {
        const active = it.key === loc.pathname;
        return (
          <div key={it.key} onClick={() => (it.key === "__more" ? onMore() : nav(it.key))}
            style={{ flex: 1, display: "flex", flexDirection: "column", alignItems: "center",
              justifyContent: "center", cursor: "pointer", fontSize: 12,
              color: active ? "#5b8cff" : "inherit", opacity: active ? 1 : 0.7 }}>
            <span style={{ fontSize: 18 }}>{it.icon}</span>
            <span>{it.label}</span>
          </div>
        );
      })}
    </div>
  );
}
```

`src/components/MoreDrawer.tsx`:

```tsx
import { Drawer, Menu } from "antd";
import { useNavigate } from "react-router-dom";
import { NAV_MORE } from "./SideNav";

export function MoreDrawer({ open, onClose }: { open: boolean; onClose: () => void }) {
  const nav = useNavigate();
  return (
    <Drawer placement="bottom" height="auto" open={open} onClose={onClose} title="更多">
      <Menu mode="inline" items={NAV_MORE}
        onClick={(e) => { nav(e.key); onClose(); }} style={{ borderInlineEnd: "none" }} />
    </Drawer>
  );
}
```

- [ ] **Step 4: Run, expect PASS** — `npx vitest run src/components/BottomTabBar.test.tsx`

- [ ] **Step 5: Commit**

```bash
git add src/components/SideNav.tsx src/components/BottomTabBar.tsx src/components/MoreDrawer.tsx src/components/BottomTabBar.test.tsx
git commit -m "feat(frontend): responsive nav (SideNav + BottomTabBar + MoreDrawer)"
```

---

### Task 4: 响应式骨架(重写 App.tsx)

**Files:**
- Modify: `src/App.tsx`
- Test: `src/App.test.tsx`(更新现有)

- [ ] **Step 1: Update test** — 现有 `src/App.test.tsx` 可能断言旧菜单文案。改成验证两态渲染。读现有文件后,替换其用例为:

```tsx
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, it, expect } from "vitest";
import { ThemeProvider } from "./theme/ThemeProvider";
import App from "./App";

function renderApp() {
  return render(
    <ThemeProvider><MemoryRouter><App /></MemoryRouter></ThemeProvider>);
}

describe("App shell", () => {
  it("renders the dashboard route by default", () => {
    renderApp();
    // 看板页有"现金"等统计;若数据未加载至少标题区存在
    expect(document.querySelector("#app-shell, .ant-layout")).toBeTruthy();
  });
});
```

> 若现有 App.test.tsx 内容更具体,保留其仍成立的断言,仅移除对已删除菜单结构的断言。

- [ ] **Step 2: Run, expect FAIL or stale** — `npx vitest run src/App.test.tsx`

- [ ] **Step 3: Implement** — 用以下内容替换 `src/App.tsx`:

```tsx
import { useState } from "react";
import { Layout, Grid } from "antd";
import { Routes, Route } from "react-router-dom";
import { Dashboard } from "./pages/Dashboard";
import { ScreenerPool } from "./pages/ScreenerPool";
import { TrackPage } from "./pages/TrackPage";
import { ResearchPage } from "./pages/ResearchPage";
import { BacktestPage } from "./pages/BacktestPage";
import { DecisionsPage } from "./pages/DecisionsPage";
import { SideNav } from "./components/SideNav";
import { BottomTabBar } from "./components/BottomTabBar";
import { MoreDrawer } from "./components/MoreDrawer";
import { ThemeToggle } from "./components/ThemeToggle";

function AppRoutes() {
  return (
    <Routes>
      <Route path="/" element={<Dashboard />} />
      <Route path="/screener" element={<ScreenerPool />} />
      <Route path="/track" element={<TrackPage />} />
      <Route path="/decisions" element={<DecisionsPage />} />
      <Route path="/research" element={<ResearchPage />} />
      <Route path="/backtest" element={<BacktestPage />} />
    </Routes>
  );
}

export default function App() {
  const screens = Grid.useBreakpoint();
  const isMobile = !screens.md;
  const [moreOpen, setMoreOpen] = useState(false);

  const header = (
    <Layout.Header style={{ display: "flex", alignItems: "center",
      justifyContent: "space-between", paddingInline: 16,
      background: "var(--ant-color-bg-container)" }}>
      <span style={{ fontSize: 16, fontWeight: 700 }}>A股 · 多智能体交易</span>
      <ThemeToggle />
    </Layout.Header>
  );

  if (isMobile) {
    return (
      <Layout id="app-shell" style={{ minHeight: "100vh" }}>
        {header}
        <Layout.Content style={{ padding: 12, paddingBottom: 72 }}>
          <AppRoutes />
        </Layout.Content>
        <BottomTabBar onMore={() => setMoreOpen(true)} />
        <MoreDrawer open={moreOpen} onClose={() => setMoreOpen(false)} />
      </Layout>
    );
  }

  return (
    <Layout id="app-shell" style={{ minHeight: "100vh" }}>
      <Layout.Sider theme="light" breakpoint="lg" collapsedWidth="0">
        <div style={{ height: 48, margin: 12, fontWeight: 700 }}>A股看板</div>
        <SideNav />
      </Layout.Sider>
      <Layout>
        {header}
        <Layout.Content style={{ padding: 24 }}>
          <AppRoutes />
        </Layout.Content>
      </Layout>
    </Layout>
  );
}
```

- [ ] **Step 4: Run, expect PASS** — `npx vitest run src/App.test.tsx`

- [ ] **Step 5: Commit**

```bash
git add src/App.tsx src/App.test.tsx
git commit -m "feat(frontend): responsive app shell (desktop sider / mobile tabbar + theme toggle)"
```

---

### Task 5: 写死栅格响应式化(Dashboard / BacktestPage)

**Files:**
- Modify: `src/pages/Dashboard.tsx`
- Modify: `src/pages/BacktestPage.tsx`

纯栅格改造:把 `Col span={N}` 改成响应式。不动逻辑。

- [ ] **Step 1: Dashboard** — 把三个统计卡那行(当前 `<Col span={8}>×3`)改为:每个 `<Col xs={24} sm={8}>`。即 `src/pages/Dashboard.tsx` 第 30–32 行三处 `<Col span={8}>` 改 `<Col xs={24} sm={8}>`。其余不动。

- [ ] **Step 2: BacktestPage** — 改 `src/pages/BacktestPage.tsx`:
  - 四个指标卡那行(`<Col span={6}>×4`)→ 每个 `<Col xs={12} md={6}>`(手机两列)。
  - 因子 IC 行(`<Col span={8}>×2`)→ 每个 `<Col xs={12} md={8}>`。
  - `Descriptions` 加响应式列:`column={{ xs: 1, md: 2 }}` 替换 `column={2}`。

- [ ] **Step 3: 验证** — `npx vitest run src/pages/Dashboard.test.tsx src/pages/BacktestPage.test.tsx`(应仍通过;若旧测试断言具体布局而失败,改为断言关键文本如"现金"/"年化收益"仍在)

- [ ] **Step 4: Commit**

```bash
git add src/pages/Dashboard.tsx src/pages/BacktestPage.tsx
git commit -m "feat(frontend): responsive grid for Dashboard & Backtest"
```

---

### Task 6: PicksTable → ResponsiveList(选股池)

**Files:**
- Modify: `src/components/PicksTable.tsx`
- Test: `src/components/PicksTable.test.tsx`(若不存在则新建)

先读 `src/components/PicksTable.tsx` 拿到它现有的 `columns` 与 `Pick` 字段(code/theme/first_selected_on/entry_close/ret_t1/ret_t3/ret_t5/ret_t10)。

- [ ] **Step 1: Write/Update test** — `src/components/PicksTable.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { PicksTable } from "./PicksTable";

const PICKS = [{ code: "600519.SH", theme: "白酒", first_selected_on: "2026-06-02",
  entry_close: 1500, ret_t1: 0.01, ret_t3: -0.02, ret_t5: null, ret_t10: null }];

describe("PicksTable", () => {
  it("desktop shows table header", () => {
    render(<PicksTable picks={PICKS} forceMobile={false} />);
    expect(screen.getByText("代码")).toBeInTheDocument();
  });
  it("mobile shows a card with code + theme", () => {
    render(<PicksTable picks={PICKS} forceMobile={true} />);
    expect(screen.getByText("600519.SH")).toBeInTheDocument();
    expect(screen.getByText("白酒")).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run, expect FAIL** — `npx vitest run src/components/PicksTable.test.tsx`

- [ ] **Step 3: Implement** — 改 `PicksTable` 用 `ResponsiveList`,新增可选 `forceMobile`,保留原 `columns`,加 `renderCard`。用 `semanticColor` 给收益上色:

```tsx
import { Card, Tag, Space } from "antd";
import { ResponsiveList } from "./ResponsiveList";
import { semanticColor } from "../theme/tokens";

// ...保留原 Pick 类型与 columns 定义...

const pct = (v: number | null) => v == null ? "—" : `${(v * 100).toFixed(1)}%`;

export function PicksTable({ picks, forceMobile }:
  { picks: Pick[]; forceMobile?: boolean }) {
  return (
    <ResponsiveList<Pick> forceMobile={forceMobile} dataSource={picks} columns={columns}
      rowKey="code"
      empty={<Empty description="暂无选股,先跑 run_screener.py" />}
      renderCard={(p) => (
        <Card size="small">
          <Space split="·">
            <b>{p.code}</b><Tag>{p.theme}</Tag><span>{p.first_selected_on}</span>
          </Space>
          <div style={{ marginTop: 6 }}>
            {(["ret_t1","ret_t3","ret_t5","ret_t10"] as const).map((k) => (
              <Tag key={k} color={semanticColor(p[k])}>{k.replace("ret_","T+")} {pct(p[k])}</Tag>
            ))}
          </div>
        </Card>
      )} />
  );
}
```

> 实现时:保留文件里原有的 `columns` 与 imports(`Empty` 等按需补),仅把渲染主体从 `<Table .../>` 换成上面的 `<ResponsiveList .../>`,并把组件 props 加上 `forceMobile?`。

- [ ] **Step 4: Run, expect PASS** — `npx vitest run src/components/PicksTable.test.tsx`

- [ ] **Step 5: Commit**

```bash
git add src/components/PicksTable.tsx src/components/PicksTable.test.tsx
git commit -m "feat(frontend): PicksTable responsive (cards on mobile)"
```

---

### Task 7: TrackTable → ResponsiveList(跟踪)

**Files:**
- Modify: `src/components/TrackTable.tsx`
- Test: `src/components/TrackTable.test.tsx`(新建/更新)

先读 `src/components/TrackTable.tsx` 拿到 `Track` 字段(含 code/name/signal/buy_price/ret_since/max_gain/max_drawdown/ret_t1..t10/last_close 等)与 `onRemove(code,on)` 签名。

- [ ] **Step 1: Write test** — `src/components/TrackTable.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { TrackTable } from "./TrackTable";

const ROWS = [{ code: "601991.SH", added_on: "2026-06-02", name: "大唐发电",
  entry_close: 9.18, ret_since: -0.04, max_gain: 0, max_drawdown: -0.04,
  last_close: 8.81, signal: "buy", buy_price: 8.54,
  ret_t1: null, ret_t3: null, ret_t5: null, ret_t10: null }];

describe("TrackTable", () => {
  it("mobile card shows name + code", () => {
    render(<TrackTable rows={ROWS as any} onRemove={vi.fn()} forceMobile={true} />);
    expect(screen.getByText("大唐发电")).toBeInTheDocument();
    expect(screen.getByText("601991.SH")).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run, expect FAIL** — `npx vitest run src/components/TrackTable.test.tsx`

- [ ] **Step 3: Implement** — 改 `TrackTable`:加 `forceMobile?`,主体换 `ResponsiveList`,保留原 `columns` 与删除按钮(在卡片里也提供"移除"),收益用 `semanticColor`:

```tsx
// renderCard 关键:
renderCard={(r) => (
  <Card size="small" extra={
    <a onClick={() => onRemove(r.code, r.added_on)}>移除</a>}>
    <Space split="·">
      <b>{r.name || r.code}</b><span>{r.code}</span>
      {r.signal === "buy" && <Tag color="red">buy@{r.buy_price}</Tag>}
    </Space>
    <div style={{ marginTop: 6 }}>
      <Tag color={semanticColor(r.ret_since)}>至今 {(r.ret_since*100).toFixed(1)}%</Tag>
      <Tag color={semanticColor(r.max_gain)}>最大涨 {(r.max_gain*100).toFixed(1)}%</Tag>
      <Tag color={semanticColor(r.max_drawdown)}>最大回 {(r.max_drawdown*100).toFixed(1)}%</Tag>
    </div>
  </Card>
)}
```

> 列名/字段以现有 `TrackTable.tsx` 为准;`added_on` 是删除回调要用的日期键。桌面 Table 与现有列保持不变,只把外层从 `<Table>` 换 `<ResponsiveList>` 并透传 `onRowClick` 可不设。

- [ ] **Step 4: Run, expect PASS** — `npx vitest run src/components/TrackTable.test.tsx`

- [ ] **Step 5: Commit**

```bash
git add src/components/TrackTable.tsx src/components/TrackTable.test.tsx
git commit -m "feat(frontend): TrackTable responsive (cards on mobile)"
```

---

### Task 8: PositionsTable + DiscoveryPanel → ResponsiveList(看板内表格)

**Files:**
- Modify: `src/components/PositionsTable.tsx`
- Modify: `src/components/DiscoveryPanel.tsx`
- Test: `src/components/PositionsTable.test.tsx`(新建)

先读两文件拿字段。`PositionsTable` props 为 `positions: {code,shares,cost}[]`;`DiscoveryPanel` 自取 `/api/discovery` 列表。

- [ ] **Step 1: Write test** — `src/components/PositionsTable.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { PositionsTable } from "./PositionsTable";

describe("PositionsTable", () => {
  it("mobile card shows code and shares", () => {
    render(<PositionsTable positions={[{ code: "600519.SH", shares: 100, cost: 1500 }]}
      forceMobile={true} />);
    expect(screen.getByText("600519.SH")).toBeInTheDocument();
    expect(screen.getByText(/100/)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run, expect FAIL** — `npx vitest run src/components/PositionsTable.test.tsx`

- [ ] **Step 3: Implement**
  - `PositionsTable`:加 `forceMobile?`,换 `ResponsiveList`,`renderCard` 显示 `代码/股数/成本`(Card + Space)。
  - `DiscoveryPanel`:把内部 `<Table>` 换 `ResponsiveList`,`renderCard` 显示 代码 + 评分/关键因子(按现有列字段),内部自己有 state,加一个本地 `forceMobile` 不必要——可不传(走真实断点)。仅做 Table→ResponsiveList 替换 + renderCard。

- [ ] **Step 4: Run, expect PASS** — `npx vitest run src/components/PositionsTable.test.tsx`;并 `npx vitest run src/pages/Dashboard.test.tsx`(确认看板不崩)

- [ ] **Step 5: Commit**

```bash
git add src/components/PositionsTable.tsx src/components/DiscoveryPanel.tsx src/components/PositionsTable.test.tsx
git commit -m "feat(frontend): PositionsTable & DiscoveryPanel responsive"
```

---

### Task 9: 决策列表/面板 → ResponsiveList(DecisionsPage + DecisionsPanel)

**Files:**
- Modify: `src/pages/DecisionsPage.tsx`
- Modify: `src/components/DecisionsPanel.tsx`

`DecisionsPage` 左侧列表当前用 `<Table>`(列:代码/动作 Tag/状态),右侧 `ConclusionCard + RoleStages`。手机上左右 `Col span={8}/{16}` 要堆叠,且列表转卡片。

- [ ] **Step 1: 改 DecisionsPage 栅格** — 左右 `Col` 改 `xs={24} md={8}` 和 `xs={24} md={16}`。

- [ ] **Step 2: 列表换 ResponsiveList** — 把左侧 `<Table>` 换成:

```tsx
<ResponsiveList<ListItem> dataSource={rows} columns={columns} rowKey="id"
  onRowClick={(r) => setSel(r.id)}
  empty={<Empty description="暂无决策,先跑 run_decisions.py" />}
  renderCard={(r) => (
    <Card size="small">
      <Space split="·"><b>{r.code}</b>
        <Tag color={ACTION_COLOR[r.action] || "default"}>{r.action}</Tag>
        <span>{r.status}</span></Space>
    </Card>
  )} />
```

(`ResponsiveList` 已 import;移除原 Table 直用逻辑,`onRow` 改由 `onRowClick`。)

- [ ] **Step 3: DecisionsPanel(看板内)** — 同法把 `<Table>` 换 `ResponsiveList`,`renderCard` 显示 代码 + 动作 Tag + 信心 + 批准/驳回按钮(PENDING 时);展开的 reasoning 在手机卡片里用 `Typography.Paragraph` 折叠显示首段即可。保留 approve/reject 逻辑不变。

- [ ] **Step 4: 验证** — `npx vitest run src/pages/DecisionsPage.test.tsx`(现有测试默认走移动态——jsdom 断点为假——应仍能查到"空仓观望"/"分析师团";如失败,调整为给 ResponsiveList 不影响详情区渲染即可,详情区不经过 ResponsiveList)。

- [ ] **Step 5: Commit**

```bash
git add src/pages/DecisionsPage.tsx src/components/DecisionsPanel.tsx
git commit -m "feat(frontend): decisions list responsive (cards on mobile)"
```

---

### Task 10: ResearchPage 响应式(栅格 + 列表卡片)

**Files:**
- Modify: `src/pages/ResearchPage.tsx`

- [ ] **Step 1: 栅格** — 左右 `Col span={10}/{14}` 改 `xs={24} md={10}` 和 `xs={24} md={14}`。

- [ ] **Step 2: 列表换 ResponsiveList** — 把左侧 `<Table>`(列:代码/情绪 Tag/日期)换 `ResponsiveList`,`onRowClick={(r)=>setSel(r)}`,`renderCard` 显示 代码 + 情绪 Tag(用 `semanticColor(sentiment)`)+ 日期;情绪 Tag 颜色由 `v>0.1?red:v<-0.1?green` 改用 `semanticColor`。

- [ ] **Step 3: 验证** — `npx vitest run src/pages/ResearchPage.test.tsx`(应仍查到 `600519.SH`)。

- [ ] **Step 4: Commit**

```bash
git add src/pages/ResearchPage.tsx
git commit -m "feat(frontend): ResearchPage responsive (cards on mobile)"
```

---

### Task 11: 全量验证 + 构建 + 重新部署

**Files:** 无新增(收尾)

- [ ] **Step 1: 全量前端测试** — `cd frontend && npx vitest run`
  Expected: 全部测试文件 PASS(含新增的 theme/ResponsiveList/BottomTabBar/各表测试 + 原有页面测试)。若个别旧测试因结构变动失败,按"断言关键文本仍在"的原则修正它们,不要降低覆盖。

- [ ] **Step 2: 构建(同源 API)** — `VITE_API_BASE="" npm run build`
  Expected: `tsc -b && vite build` 无类型错误;`dist/` 生成。

- [ ] **Step 3: 重新部署** — Caddy 直接托管 `frontend/dist`,无需重启(静态文件已更新);如需确保缓存刷新可 reload:
  `cd /root/caddy && ./caddy reload --config /root/caddy/Caddyfile`
  然后 `curl -s --noproxy '*' --resolve cd.makezhan.xyz:5173:127.0.0.1 https://cd.makezhan.xyz:5173/ | grep -c 'id="root"'` 应为 1。

- [ ] **Step 4: 人工核对(用户)** — 用户在手机/桌面分别打开 `https://cd.makezhan.xyz:5173`:手机出现底部 TabBar + 卡片列表、能切主题;桌面侧栏 + 表格。

> 注:本环境无浏览器,Task 1–10 靠 vitest + build 把关;真机观感由用户在 Step 4 验收,发现问题再迭代。

---

## 备注

- 不改后端、不改任何 API 契约与业务逻辑(下单/批准/驳回/各列表数据流不变)。
- ECharts(EquityChart/LayerBars)沿用,仅随主题背景变化;如深色下图表底色突兀,可在后续微调,不在本计划强制。
- 语义色 `semanticColor` 统一红涨绿跌;BUY=红/SELL=绿/HOLD=灰沿用。
- 所有断点相关组件提供 `forceMobile?` 测试钩子,保证 vitest 可确定性地验证两态。
