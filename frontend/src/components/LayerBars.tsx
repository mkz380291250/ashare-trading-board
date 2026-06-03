import { useEffect, useRef } from "react";
import * as echarts from "echarts";

export function LayerBars({ layers }: { layers: number[] }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!ref.current) return;
    const chart = echarts.init(ref.current);
    chart.setOption({
      xAxis: { type: "category", data: layers.map((_, i) => `L${i + 1}`) },
      yAxis: { type: "value", axisLabel: { formatter: (v: number) => `${(v * 100).toFixed(1)}%` } },
      series: [{ type: "bar", data: layers.map((v) => +(v * 100).toFixed(2)) }],
      tooltip: { trigger: "axis" },
    });
    const onResize = () => chart.resize();
    window.addEventListener("resize", onResize);
    return () => { window.removeEventListener("resize", onResize); chart.dispose(); };
  }, [layers]);
  return <div ref={ref} style={{ height: 280 }} />;
}
