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

export const UP = "#f5222d";
export const DOWN = "#13c281";
export function semanticColor(v: number | null | undefined): string | undefined {
  if (v == null || v === 0) return undefined;
  return v > 0 ? UP : DOWN;
}
