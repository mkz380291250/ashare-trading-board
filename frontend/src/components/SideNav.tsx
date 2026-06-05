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
