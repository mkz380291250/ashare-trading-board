import { Layout, Menu } from "antd";
import { Routes, Route, useNavigate, useLocation } from "react-router-dom";
import { Dashboard } from "./pages/Dashboard";
import { ScreenerPool } from "./pages/ScreenerPool";
import { TrackPage } from "./pages/TrackPage";
import { ResearchPage } from "./pages/ResearchPage";
import { BacktestPage } from "./pages/BacktestPage";
import { DecisionsPage } from "./pages/DecisionsPage";

const ITEMS = [
  { key: "/", label: "交易看板" },
  { key: "/screener", label: "选股池" },
  { key: "/track", label: "跟踪" },
  { key: "/decisions", label: "决策" },
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
            <Route path="/track" element={<TrackPage />} />
            <Route path="/decisions" element={<DecisionsPage />} />
            <Route path="/research" element={<ResearchPage />} />
            <Route path="/backtest" element={<BacktestPage />} />
          </Routes>
        </Layout.Content>
      </Layout>
    </Layout>
  );
}
