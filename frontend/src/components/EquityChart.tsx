import { useEffect, useRef } from "react";
import * as echarts from "echarts";

type Point = { as_of: string; total: number };

export function EquityChart({ points }: { points: Point[] }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!ref.current) return;
    const chart = echarts.init(ref.current);
    chart.setOption({
      xAxis: { type: "category", data: points.map((p) => p.as_of) },
      yAxis: { type: "value", scale: true },
      series: [{ type: "line", data: points.map((p) => p.total), smooth: true }],
      tooltip: { trigger: "axis" },
    });
    return () => chart.dispose();
  }, [points]);
  return <div ref={ref} style={{ width: "100%", height: 300 }} />;
}
