import { Switch } from "antd";
import { useTheme } from "../theme/ThemeProvider";

export function ThemeToggle() {
  const { isDark, toggle } = useTheme();
  return <Switch checked={isDark} onChange={toggle}
    checkedChildren="🌙" unCheckedChildren="☀️" aria-label="切换主题" />;
}
