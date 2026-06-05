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
