import { useEffect, useRef, useState, type CSSProperties } from "react";
import {
  createChart, CandlestickSeries, HistogramSeries, LineSeries, CrosshairMode,
  type IChartApi, type ISeriesApi,
} from "lightweight-charts";
import { UP, DOWN } from "../theme/tokens";
import { toSec, ma, macd, kdj } from "./klineMath";

export type Bar = { t: string; o: number; h: number; l: number; c: number; v: number };

const MA = [
  { n: 5, color: "#e9c46a" },
  { n: 10, color: "#4aa3ff" },
  { n: 20, color: "#c77dff" },
];

type Ind = { macd: boolean; kdj: boolean };

// TradingView Lightweight Charts(v5):蜡烛 + 成交量 + 均线 MA5/10/20,
// 可选副图 MACD / KDJ(独立 pane,可在图上方按钮切换)。A股红涨绿跌,暗色主题。
export function KLineChart({ bars, height = 440 }: { bars: Bar[]; height?: number | string }) {
  const ref = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const volRef = useRef<ISeriesApi<"Histogram"> | null>(null);
  const maRef = useRef<ISeriesApi<"Line">[]>([]);
  const macdRef = useRef<{ hist: ISeriesApi<"Histogram">; dif: ISeriesApi<"Line">; dea: ISeriesApi<"Line"> } | null>(null);
  const kdjRef = useRef<{ k: ISeriesApi<"Line">; d: ISeriesApi<"Line">; j: ISeriesApi<"Line"> } | null>(null);

  const [ind, setInd] = useState<Ind>({ macd: true, kdj: false });

  // 重建图表结构:依赖指标开关(切换时重建,盘中轮询只改数据不重建,保留缩放)。
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
      timeScale: { borderColor: "rgba(255,255,255,0.12)", timeVisible: true, secondsVisible: false },
    });
    chartRef.current = chart;

    maRef.current = MA.map((m) =>
      chart.addSeries(LineSeries, {
        color: m.color, lineWidth: 1,
        priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false,
      }));

    candleRef.current = chart.addSeries(CandlestickSeries, {
      upColor: UP, downColor: DOWN, borderVisible: false, wickUpColor: UP, wickDownColor: DOWN,
    });

    const vol = chart.addSeries(HistogramSeries, { priceFormat: { type: "volume" }, priceScaleId: "" });
    vol.priceScale().applyOptions({ scaleMargins: { top: 0.84, bottom: 0 } });
    volRef.current = vol;

    // 副图按需挂到独立 pane(主图为 pane 0,依次往下排)。
    macdRef.current = null;
    kdjRef.current = null;
    if (ind.macd) {
      const p = 1;
      const hist = chart.addSeries(HistogramSeries, { priceLineVisible: false, lastValueVisible: false }, p);
      const dif = chart.addSeries(LineSeries, { color: "#e9c46a", lineWidth: 1, priceLineVisible: false, lastValueVisible: false }, p);
      const dea = chart.addSeries(LineSeries, { color: "#4aa3ff", lineWidth: 1, priceLineVisible: false, lastValueVisible: false }, p);
      macdRef.current = { hist, dif, dea };
    }
    if (ind.kdj) {
      const p = ind.macd ? 2 : 1;
      const k = chart.addSeries(LineSeries, { color: "#e9c46a", lineWidth: 1, priceLineVisible: false, lastValueVisible: false }, p);
      const d = chart.addSeries(LineSeries, { color: "#4aa3ff", lineWidth: 1, priceLineVisible: false, lastValueVisible: false }, p);
      const j = chart.addSeries(LineSeries, { color: "#c77dff", lineWidth: 1, priceLineVisible: false, lastValueVisible: false }, p);
      kdjRef.current = { k, d, j };
    }
    // 主图占大头,副图各占小条。
    try {
      const panes = chart.panes();
      panes[0]?.setStretchFactor(3);
      for (let i = 1; i < panes.length; i++) panes[i]?.setStretchFactor(1);
    } catch { /* mock 环境无 panes() */ }

    return () => { chart.remove(); chartRef.current = null; };
  }, [ind]);

  // 喂数据:bars 或指标变化时刷新各序列。
  useEffect(() => {
    if (!candleRef.current) return;
    candleRef.current.setData(bars.map((b) => ({ time: toSec(b.t), open: b.o, high: b.h, low: b.l, close: b.c })));
    volRef.current?.setData(bars.map((b) => ({
      time: toSec(b.t), value: b.v,
      color: b.c >= b.o ? "rgba(245,34,45,0.45)" : "rgba(19,194,129,0.45)",
    })));
    maRef.current.forEach((s, i) => s.setData(ma(bars, MA[i].n)));

    if (macdRef.current) {
      const m = macd(bars);
      macdRef.current.hist.setData(m.hist.map((h) => ({
        time: h.time, value: h.value,
        color: h.up ? "rgba(245,34,45,0.5)" : "rgba(19,194,129,0.5)",
      })));
      macdRef.current.dif.setData(m.dif);
      macdRef.current.dea.setData(m.dea);
    }
    if (kdjRef.current) {
      const r = kdj(bars);
      kdjRef.current.k.setData(r.k);
      kdjRef.current.d.setData(r.d);
      kdjRef.current.j.setData(r.j);
    }
    chartRef.current?.timeScale().fitContent();
  }, [bars, ind]);

  const chip = (on: boolean): CSSProperties => ({
    cursor: "pointer", fontSize: 12, lineHeight: "20px", padding: "0 10px", borderRadius: 6,
    border: "1px solid rgba(255,255,255,0.14)", userSelect: "none",
    color: on ? "#fff" : "#9aa4b2", background: on ? "rgba(91,140,255,0.25)" : "transparent",
  });

  return (
    <div style={{ display: "flex", flexDirection: "column", width: "100%", height }}>
      <div style={{ display: "flex", gap: 8, marginBottom: 6, flexShrink: 0 }}>
        <span style={chip(ind.macd)} onClick={() => setInd((s) => ({ ...s, macd: !s.macd }))}>MACD</span>
        <span style={chip(ind.kdj)} onClick={() => setInd((s) => ({ ...s, kdj: !s.kdj }))}>KDJ</span>
      </div>
      <div ref={ref} style={{ flex: 1, minHeight: 0 }} />
    </div>
  );
}
