import { createContext, useCallback, useContext, useState, type ReactNode } from "react";
import { StockChartModal } from "./StockChartModal";

type Ctx = { openChart: (code: string, name?: string) => void };

// 默认 no-op:无 Provider 时(如单测里孤立渲染某个列表)StockLink 仍能渲染,
// 点击不报错只是不弹图。真实 App 在 main.tsx 根部已包 Provider。
const StockChartContext = createContext<Ctx>({ openChart: () => {} });

export function useStockChart(): Ctx {
  return useContext(StockChartContext);
}

// 全局持有「当前打开的图」状态,在根部渲染一个 StockChartModal。
// 任意组件用 useStockChart().openChart(code, name) 即可弹出 K 线。
export function StockChartProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<{ code: string; name?: string; open: boolean }>({
    code: "", open: false,
  });
  const openChart = useCallback(
    (code: string, name?: string) => setState({ code, name, open: true }), []);
  const onClose = useCallback(() => setState((s) => ({ ...s, open: false })), []);

  return (
    <StockChartContext.Provider value={{ openChart }}>
      {children}
      <StockChartModal code={state.code} name={state.name}
                       open={state.open} onClose={onClose} />
    </StockChartContext.Provider>
  );
}
