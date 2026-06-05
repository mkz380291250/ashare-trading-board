import type { ReactNode } from "react";
import { useStockChart } from "./StockChartProvider";

// 可点的股票链接。默认显示「名称(代码)」;传 children 可自定义显示文本
// (如只显示代码),点击仍以 name 打开 K 线。stopPropagation 避免触发所在行的选中/详情。
export function StockLink({ code, name, children }: {
  code: string; name?: string | null; children?: ReactNode;
}) {
  const { openChart } = useStockChart();
  const label = name ? `${name}(${code})` : code;
  return (
    <a
      style={{ cursor: "pointer" }}
      onClick={(e) => {
        e.stopPropagation();
        openChart(code, name ?? undefined);
      }}
    >
      {children ?? label}
    </a>
  );
}
