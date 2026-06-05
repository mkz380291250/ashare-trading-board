import { useEffect, useRef } from "react";
import { init, dispose, type Chart, type KLineData } from "klinecharts";

export type Bar = { t: string; o: number; h: number; l: number; c: number; v: number };

function toKLine(bars: Bar[]): KLineData[] {
  return bars.map((b) => ({
    timestamp: new Date(b.t).getTime(),
    open: b.o, high: b.h, low: b.l, close: b.c, volume: b.v,
  }));
}

// KLineCharts(v10)封装:蜡烛 + 成交量 + 十字光标(库自带)。
// 只读传入的 bars,刷新由父组件换 bars 触发(配合 resetData 重新喂数)。
export function KLineChart({ bars }: { bars: Bar[] }) {
  const ref = useRef<HTMLDivElement>(null);
  const chartRef = useRef<Chart | null>(null);
  const dataRef = useRef<KLineData[]>([]);

  useEffect(() => {
    if (!ref.current) return;
    const chart = init(ref.current);
    chartRef.current = chart;
    chart?.createIndicator("VOL");
    chart?.setSymbol({ ticker: "K" });
    chart?.setPeriod({ span: 1, type: "minute" });
    chart?.setDataLoader({
      getBars: ({ callback }) => callback(dataRef.current, false),
    });
    return () => {
      if (chart) dispose(chart);
      chartRef.current = null;
    };
  }, []);

  useEffect(() => {
    dataRef.current = toKLine(bars);
    chartRef.current?.resetData();
  }, [bars]);

  return <div ref={ref} style={{ width: "100%", height: 420 }} />;
}
