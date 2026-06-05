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
