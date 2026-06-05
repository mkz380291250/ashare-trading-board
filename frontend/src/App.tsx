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
