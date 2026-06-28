import { useEffect, useRef } from "react";
import * as echarts from "echarts";

type Point = { as_of: string; ic: number | null; rank_ic: number | null; n: number };

export function ForwardICChart({ points }: { points: Point[] }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!ref.current) return;
    const chart = echarts.init(ref.current);
    chart.setOption({
      tooltip: { trigger: "axis" },
      legend: { data: ["IC", "RankIC"] },
      xAxis: { type: "category", data: points.map((p) => p.as_of) },
      yAxis: { type: "value", scale: true },
      series: [
        { name: "IC", type: "line", data: points.map((p) => p.ic), smooth: true },
        { name: "RankIC", type: "line", data: points.map((p) => p.rank_ic), smooth: true,
          markLine: { silent: true, data: [{ yAxis: 0.02 }] } },
      ],
    });
    return () => chart.dispose();
  }, [points]);
  return <div ref={ref} style={{ width: "100%", height: 300 }} />;
}
