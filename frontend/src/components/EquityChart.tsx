import { useEffect, useRef } from "react";
import * as echarts from "echarts";

type Point = { as_of: string; total: number; drawdown?: number };

export function EquityChart({ points }: { points: Point[] }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!ref.current) return;
    const chart = echarts.init(ref.current);
    const hasDd = points.some((p) => p.drawdown != null);
    const series: any[] = [
      { name: "净值", type: "line", data: points.map((p) => p.total), smooth: true },
    ];
    if (hasDd) {
      series.push({ name: "回撤", type: "line", yAxisIndex: 1, areaStyle: {},
        data: points.map((p) => (p.drawdown != null ? p.drawdown * 100 : null)), smooth: true });
    }
    chart.setOption({
      tooltip: { trigger: "axis" },
      xAxis: { type: "category", data: points.map((p) => p.as_of) },
      yAxis: hasDd
        ? [{ type: "value", scale: true }, { type: "value", name: "回撤%", max: 0 }]
        : { type: "value", scale: true },
      series,
    });
    return () => chart.dispose();
  }, [points]);
  return <div ref={ref} style={{ width: "100%", height: 300 }} />;
}
