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
