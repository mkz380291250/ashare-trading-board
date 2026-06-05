import { useEffect, useRef } from "react";
import {
  createChart, CandlestickSeries, HistogramSeries, LineSeries, CrosshairMode,
  type IChartApi, type ISeriesApi, type UTCTimestamp,
} from "lightweight-charts";
import { UP, DOWN } from "../theme/tokens";

export type Bar = { t: string; o: number; h: number; l: number; c: number; v: number };

// 把「字面北京时间」转成 UTC 秒,让坐标轴直接显示原始 HH:MM(与浏览器时区无关)。
function toSec(t: string): UTCTimestamp {
  const m = t.match(/(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})/);
  if (!m) return Math.floor(new Date(t).getTime() / 1000) as UTCTimestamp;
  return Math.floor(Date.UTC(+m[1], +m[2] - 1, +m[3], +m[4], +m[5]) / 1000) as UTCTimestamp;
}

function ma(bars: Bar[], n: number) {
  const out: { time: UTCTimestamp; value: number }[] = [];
  let sum = 0;
  for (let i = 0; i < bars.length; i++) {
    sum += bars[i].c;
    if (i >= n) sum -= bars[i - n].c;
    if (i >= n - 1) out.push({ time: toSec(bars[i].t), value: +(sum / n).toFixed(3) });
  }
  return out;
}

const MA = [
  { n: 5, color: "#e9c46a" },
  { n: 10, color: "#4aa3ff" },
  { n: 20, color: "#c77dff" },
];

// TradingView Lightweight Charts(v5):蜡烛 + 成交量 + 均线 MA5/10/20。
// A股红涨绿跌,暗色主题,十字光标。props 不变(bars: Bar[]),父组件换 bars 即刷新。
export function KLineChart({ bars }: { bars: Bar[] }) {
  const ref = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const volRef = useRef<ISeriesApi<"Histogram"> | null>(null);
  const maRef = useRef<ISeriesApi<"Line">[]>([]);

  useEffect(() => {
    if (!ref.current) return;
    const chart = createChart(ref.current, {
      autoSize: true,
      layout: { background: { color: "transparent" }, textColor: "#9aa4b2", fontSize: 11 },
      grid: {
        vertLines: { color: "rgba(255,255,255,0.05)" },
        horzLines: { color: "rgba(255,255,255,0.05)" },
      },
      crosshair: { mode: CrosshairMode.Normal },
      rightPriceScale: { borderColor: "rgba(255,255,255,0.12)" },
      timeScale: {
        borderColor: "rgba(255,255,255,0.12)",
        timeVisible: true, secondsVisible: false,
      },
    });
    chartRef.current = chart;

    maRef.current = MA.map((m) =>
      chart.addSeries(LineSeries, {
        color: m.color, lineWidth: 1,
        priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false,
      }));

    candleRef.current = chart.addSeries(CandlestickSeries, {
      upColor: UP, downColor: DOWN, borderVisible: false,
      wickUpColor: UP, wickDownColor: DOWN,
    });

    const vol = chart.addSeries(HistogramSeries, {
      priceFormat: { type: "volume" }, priceScaleId: "",
    });
    vol.priceScale().applyOptions({ scaleMargins: { top: 0.84, bottom: 0 } });
    volRef.current = vol;

    return () => { chart.remove(); chartRef.current = null; };
  }, []);

  useEffect(() => {
    if (!candleRef.current) return;
    candleRef.current.setData(bars.map((b) => ({
      time: toSec(b.t), open: b.o, high: b.h, low: b.l, close: b.c,
    })));
    volRef.current?.setData(bars.map((b) => ({
      time: toSec(b.t), value: b.v,
      color: b.c >= b.o ? "rgba(245,34,45,0.45)" : "rgba(19,194,129,0.45)",
    })));
    maRef.current.forEach((s, i) => s.setData(ma(bars, MA[i].n)));
    chartRef.current?.timeScale().fitContent();
  }, [bars]);

  return <div ref={ref} style={{ width: "100%", height: 440 }} />;
}
